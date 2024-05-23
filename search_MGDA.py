# -*- coding: utf-8 -*-
"""SSA_3.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1nzIJ0UFb0QTCO0vsFNQS14Z6iXpLOZMa
"""


# Creating the CIFAR10 Model
import torch
import torch.nn as nn
import torch.optim as optim
import torchvision
from torchvision import datasets, transforms
import torch.nn.functional as F
import numpy as np
import json
import os
import random
from torch.utils.data import DataLoader, Dataset,Subset
import matplotlib.pyplot as plt
from torch.nn.functional import softmax
from PIL import Image
import torchvision.transforms.functional as TF
import copy
import warnings
warnings.filterwarnings("ignore")

import argparse
import os
import time
from bitstring import Bits
import torch.utils.data
import torchvision.transforms as transforms
import torchvision.datasets as datasets
from models import quan_resnet
from models.quantization import *

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# path of cifar10 data on yout device
cifar_root = "./data"

# path of the quantized model
model_root = "cifar_resnet_quan_8"
float_model_root = "Versatile-Weight-Attack/cifar_resnet_float"

######################################################### utils ###################################################################s

# Function to compute the custom loss (objective function)
def compute_loss(outputs, target_class_index, auglag_ori, auglag, lambda_reg1):
    # Fi(θ, x) - part that maximizes the target class probability
    target_probability = outputs[0, target_class_index]  # Keep it as a tensor

    n_bit_flips = torch.sum((auglag_ori.w_twos.detach() != auglag.w_twos).float())
    l1_penalty = lambda_reg1 * n_bit_flips

    # Objective: Maximize target_probability while minimizing weight perturbation (number of bit flips)
    loss = target_probability - l1_penalty 
    return loss

def load_model(arch, bit_length):
    model_path = model_root
    arch = arch + "_mid"

    model = torch.nn.DataParallel(quan_resnet.__dict__[arch](10, bit_length))

    model.to(device)

    # model.load_state_dict(torch.load(os.path.join(model_path, "model.th"))["state_dict"])
    state_dict = torch.load(os.path.join(model_path, "model.th"), map_location=device)["state_dict"]
    model.load_state_dict(state_dict)

    if isinstance(model, torch.nn.DataParallel):
        model = model.module

    for m in model.modules():
        if isinstance(m, quan_Linear):
            m.__reset_stepsize__()
            m.__reset_weight__()
            weight = m.weight.data.detach().cpu().numpy()
            bias = m.bias.data.detach().cpu().numpy()
            # step_size = np.array([m.step_size.detach().cpu().numpy()])[0]
            step_size = np.float32(m.step_size.detach().cpu().numpy())
    return weight, bias, step_size


def load_data(arch, bit_length):
    mid_dim = 64
    model_path = model_root
    arch = arch + "_mid"

    model = torch.nn.DataParallel(quan_resnet.__dict__[arch](10, bit_length))

    model.to(device)

    state_dict = torch.load(os.path.join(model_path, "model.th"), map_location=device)["state_dict"]
    model.load_state_dict(state_dict)

    if isinstance(model, torch.nn.DataParallel):
        model = model.module

    normalize = transforms.Normalize(mean=[0.4914, 0.4822, 0.4465],
                                     std=[0.2023, 0.1994, 0.2010])

    val_set = datasets.CIFAR10(root=cifar_root, train=False, transform=transforms.Compose([
        transforms.ToTensor(),
        normalize,
    ]))

    val_loader = torch.utils.data.DataLoader(
        dataset=val_set,
        batch_size=256, shuffle=False, pin_memory=True)

    mid_out = np.zeros([10000, mid_dim])
    labels = np.zeros([10000])
    start = 0
    model.eval()
    for i, (input, target) in enumerate(val_loader):
        input_var = torch.autograd.Variable(input, volatile=True).to(device)

        # compute output before FC layer.
        output = model(input_var)
        mid_out[start: start + 256] = output.detach().cpu().numpy()

        labels[start: start + 256] = target.numpy()
        start += 256

    mid_out = torch.tensor(mid_out).float().to(device)
    labels = torch.tensor(labels).float()

    return mid_out, labels

def find_differing_weights(auglag1, auglag2):
    # Reconstruct the weights from w_twos for both instances
    weights1 = auglag1.get_full_precision_weights()
    weights2 = auglag2.get_full_precision_weights()

    # Find where the weights differ
    differing_indices = torch.nonzero(weights1 != weights2, as_tuple=True)

    return differing_indices

############################################################################################################
####### Model definition 

class AugLag(nn.Module):
    def __init__(self, n_bits, w, b, step_size, init=False):
        super(AugLag, self).__init__()

        self.n_bits = n_bits
        self.b = nn.Parameter(torch.tensor(b).float(), requires_grad=True)

        self.w_twos = nn.Parameter(torch.zeros([w.shape[0], w.shape[1], self.n_bits]), requires_grad=True)
        self.step_size = step_size
        self.w = w

        base = [2**i for i in range(self.n_bits-1, -1, -1)]
        base[0] = -base[0]
        self.base = nn.Parameter(torch.tensor([[base]]).float())

        if init:
            self.reset_w_twos()

    def forward(self, x):

        # covert w_twos to float
        w = self.w_twos * self.base
        w = torch.sum(w, dim=2) * self.step_size

        # calculate output
        x = F.linear(x, w, self.b)

        return x

    def get_full_precision_weights(self):
      w = self.w_twos * self.base
      w = torch.sum(w, dim=2) * self.step_size
      return w

    def reset_w_twos(self):
        for i in range(self.w.shape[0]):
            for j in range(self.w.shape[1]):
                self.w_twos.data[i][j] += \
                    torch.tensor([int(b) for b in Bits(int=int(self.w[i][j]), length=self.n_bits).bin])

#####################################################################################################################################
################## Attack

def M_GDA_Attack(auglag, auglag_ori, device, target_class_index, victim_image, all_data, labels, learning_rate=0.001, lambda_reg1=1, victim_class = 0): 
    
    print(f"Learning rate is {learning_rate}, beta {lambda_reg1} victim class {victim_class}")
    victim_image = victim_image.requires_grad_(True)  # Assuming victim_image is your input tensor
    victim_image.to(device)
    outputs = auglag(victim_image)
    outputs.to(device)
    print(f"Target class {target_class_index}")
    auglag.to(device)  # Move all internal tensors to the specified device
    auglag_ori.to(device)

    #### Parameter Processing #####
    # Assuming 'outputs' is produced by your model and may be on a GPU
    device = outputs.device

    # Move 'target_class_tensor' to the same device as 'outputs'
    target_class_tensor = torch.tensor([victim_class], dtype=torch.long, device=device)

    loss_fn = nn.CrossEntropyLoss()

    # Now you can safely compute the loss
    loss = loss_fn(outputs, target_class_tensor)

    # Compute gradients
    loss.backward()

    last_linear_gradients = auglag.w_twos.grad


    accumulated_gradients = torch.zeros_like(auglag.w_twos, device=device)
    num_samples = 0

    loss_fn = nn.CrossEntropyLoss()
    idx = 0
    for image in all_data:
        label = labels[idx]
        # images, labels = images.to(device), labels.to(device)
        label = label.to(device).long()
        # Enable gradient tracking for input
        image.requires_grad_(True)

        auglag.zero_grad()  # Zero out gradients in the model

        outputs = auglag(image)  # Forward pass

        loss = loss_fn(outputs, label)  # Compute loss

        loss.backward()  # Backward pass to compute gradients

        # Accumulate gradients for 'w_twos'
        accumulated_gradients += auglag.w_twos.grad

        num_samples += 1

        idx = idx + 1
        # Manage GPU resources
        if device.type == 'cuda':
            torch.cuda.empty_cache()

    average_gradients = accumulated_gradients / num_samples

    ###### Attack #####
    num_hyperparams = 8
    start_n = 1500
    end_n = 5120
    step_n = (end_n - start_n) / (num_hyperparams - 1)

    # Store results
    results = []

    # Compute absolute gradient differences
    gradient_diff = (last_linear_gradients.abs() - average_gradients.abs()).abs()

    # Flatten the gradient differences to sort them and find the largest
    values, flat_indices = torch.sort(gradient_diff.view(-1), descending=True)

    for i in range(num_hyperparams):
        top_n = int(start_n + i * step_n)
        
        significant_flat_indices = flat_indices[:top_n]

        # Convert flat indices to actual multidimensional indices
        significant_indices = np.unravel_index(significant_flat_indices.cpu().numpy(), auglag.w_twos.shape)
        significant_indices = tuple(torch.tensor(x, device=device) for x in significant_indices)

        # Create a mask with the same shape as the parameter tensor, initialized to zero
        mask = torch.zeros_like(auglag.w_twos, device=device)

        # Set the significant indices in the mask to 1
        mask[significant_indices] = 1

        # Reset auglag.w_twos to its original state before modification compression
        with torch.no_grad():
            auglag.w_twos.copy_(auglag_ori.w_twos)

        auglag.eval()  # Set model to evaluation mode
        auglag.train()
        epochs_since_improvement = 0
        last_target_prob = 0
        epoch = 0

        outputs = auglag(victim_image)
        outputs = F.softmax(outputs, dim=1)
        current_target_prob = outputs[0, target_class_index].item()
        print(f"Gradient Desent on Testing top_n = {top_n}, target_class_prob = {current_target_prob}")

        while True:
          epoch += 1
          outputs = auglag(victim_image)
          outputs = F.softmax(outputs, dim=1)

          loss = compute_loss(outputs, target_class_index, auglag_ori, auglag, lambda_reg1)
          loss.backward(retain_graph = True)

          with torch.no_grad():
            for name, param in auglag.named_parameters():
              if name == 'w_twos':
                param.data += learning_rate * param.grad * mask
                param.data[param.data > 1] = 1.0
                param.data[param.data < 0] = 0.0

          # Check target class probability after the update
          with torch.no_grad():
              outputs = auglag(victim_image)
              outputs = F.softmax(outputs, dim=1)
              current_target_prob = outputs[0, target_class_index].item()

          print(f"Target prob is {current_target_prob}, epochs_since_improvement is {epochs_since_improvement}")
          if current_target_prob <= last_target_prob:
                epochs_since_improvement += 1
          else:
            epochs_since_improvement = 0
            last_target_prob = current_target_prob

          # Early stopping if the target class probability reaches threshold
          if current_target_prob == 1:
            #   print(f"Early stopping at epoch {epoch}. Target class probability: {current_target_prob}")
              break
        
          if epochs_since_improvement >= 20000 or epoch >= 100000:
              print(f"Early stopping at epoch {epoch}. No improvement in target class probability.")
              break

        outputs = auglag(victim_image)
        outputs = F.softmax(outputs, dim=1)
        current_target_prob = outputs[0, target_class_index].item()
        # print("Target prob is ", current_target_prob)

        parameter_modifications = auglag.w_twos.data - auglag_ori.w_twos.data

        # Flatten the modifications for processing
        modifications_flat = parameter_modifications.view(-1)
        indices = torch.argsort(torch.abs(modifications_flat))

        # Reset auglag.w_twos to its original state before modification compression
        with torch.no_grad():
            auglag.w_twos.copy_(auglag_ori.w_twos)

        auglag.eval()  # Set model to evaluation mode

        for idx in range(len(modifications_flat)):
            # Store a copy of modifications_flat before the current modification
            modifications_flat_backup = modifications_flat.clone()

            # Find indices of non-zero modifications
            non_zero_indices = torch.nonzero(modifications_flat != 0, as_tuple=False).view(-1)

            if len(non_zero_indices) == 0:
                break  # Stop if all modifications are zero

            # Index of the smallest non-zero modification
            smallest_modification_idx = non_zero_indices[torch.argmin(torch.abs(modifications_flat[non_zero_indices]))]

            # Zero out the smallest non-zero modification
            modifications_flat[smallest_modification_idx] = 0

            #   print(f"Modifying the index: {smallest_modification_idx.item()}")
            with torch.no_grad():
                # Apply the current state of modifications to the model
                auglag.w_twos.data = auglag_ori.w_twos + modifications_flat.view_as(auglag.w_twos)

                # Test the model with the current modifications
                outputs = auglag(victim_image)
                target_class_prob = F.softmax(outputs, dim=1)[0, target_class_index]

                #   print(f"Target class probability: {target_class_prob.item()}.")
                if target_class_prob.item() <= 0.5:
                    # If the threshold is not met, revert modifications_flat to its state before the last modification
                    modifications_flat = modifications_flat_backup.clone()

                    # Also revert the weights of the model to match the reverted state of modifications_flat
                    auglag.w_twos.data = auglag_ori.w_twos + modifications_flat.view_as(auglag.w_twos)

                    # print("Reverted the last modification due to drop below threshold probability.")
                    break  # Exit the loop since the threshold condition was not met
        auglag_1 = copy.deepcopy(auglag)
    
        auglag.w_twos.data[auglag.w_twos.data > 0.5] = 1.0
        auglag.w_twos.data[auglag.w_twos.data < 0.5] = 0.0

        n_bit_1 = torch.norm(auglag_ori.w_twos.data.view(-1) - auglag.w_twos.data.view(-1), p=0).item()
        n_bit_2 = torch.norm(auglag_ori.w_twos.data.view(-1) - auglag_1.w_twos.data.view(-1), p=0).item()
        print(f"N-bit1 is {n_bit_1} and N-bit2 is {n_bit_2}")

        if(n_bit_1 == 0 and n_bit_2 != 0):
            auglag = copy.deepcopy(auglag_1)

        differing_locations = find_differing_weights(auglag_ori, auglag)
        n_bit_1 = torch.norm(auglag_ori.w_twos.data.view(-1) - auglag.w_twos.data.view(-1), p=0).item()

        clean_output = auglag(all_data)

        _, pred = clean_output.cpu().topk(1, 1, True, True)
        clean_output = clean_output.detach().cpu().numpy()
        pred = pred.squeeze(1)
        acc_final_1 = len([i for i in range(len(pred)) if labels[i] == pred[i]]) / len(labels)

        outputs = auglag(victim_image)
        outputs = F.softmax(outputs, dim=1)
        current_target_prob = outputs[0, target_class_index].item()

        if(current_target_prob < 0.5):
            n_bit_1 = 0  
            acc_final_1 = 0
        results.append((top_n, n_bit_1, acc_final_1, differing_locations))
    # Find the entry with the maximum accuracy
    best_result = max(results, key=lambda x: x[2])  # Index 2 is the accuracy in each result tuple

    # Unpack the best result
    top_n, n_bit_3, acc_final, differing_locations_2 = best_result

    dim1_indices_2 = differing_locations_2[0].cpu().numpy()
    dim2_indices_2 = differing_locations_2[1].cpu().numpy()
    differing_indices_pairs_2 = list(zip(dim1_indices_2, dim2_indices_2))

    return top_n,acc_final*100, n_bit_3, differing_indices_pairs_2


def main():
    
    # Transformations for the input data
    transform = transforms.Compose(
        [transforms.ToTensor(),
        transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))])  # Normalizes the dataset

    # Load CIFAR10 training dataset
    full_trainset = datasets.CIFAR10(root='./data', train=True, download=True, transform=transform)

    # Splitting the full training set into training and validation sets
    train_size = int(0.8 * len(full_trainset))
    validation_size = len(full_trainset) - train_size
    trainset, validationset = torch.utils.data.random_split(full_trainset, [train_size, validation_size])

    trainloader = torch.utils.data.DataLoader(trainset, batch_size=4, shuffle=True, num_workers=2)
    validationloader = torch.utils.data.DataLoader(validationset, batch_size=4, shuffle=True, num_workers=2)

    # Load CIFAR10 test dataset
    testset = datasets.CIFAR10(root='./data', train=False, download=True, transform=transform)
    testloader = torch.utils.data.DataLoader(testset, batch_size=4, shuffle=False, num_workers=2)

    classes = ('plane', 'car', 'bird', 'cat', 'deer', 'dog', 'frog', 'horse', 'ship', 'truck')

    parser = argparse.ArgumentParser(description="Process a specific image based on its index.")
    parser.add_argument('--image_index', type=int, required=True, help='Index of the image to process')
    parser.add_argument('--target_class_index', type=int, required=True, help='Index of the target class to process')
    parser.add_argument('--ip_index', type=int, required=True, help='Index of the ip text file')

    args = parser.parse_args()


    """Resnet-8 quantized model(Attack)"""

    np.random.seed(512)

    args = parser.parse_args()

    os.environ["CUDA_VISIBLE_DEVICES"] = "0"

    # prepare the data
    print("Prepare data ... ")
    arch = "resnet20_quan"
    bit_length = 8

    weight, bias, step_size = load_model(arch, bit_length)
    all_data, labels = load_data(arch, bit_length)
    labels_cuda = labels.to(device)

    auglag = AugLag(bit_length, weight, bias, step_size, init=True).to(device)

    clean_output = auglag(all_data)

    _, pred = clean_output.cpu().topk(1, 1, True, True)
    clean_output = clean_output.detach().cpu().numpy()
    pred = pred.squeeze(1)
    acc_ori = len([i for i in range(len(pred)) if labels[i] == pred[i]]) / len(labels)
    
    ### Getting victim_image_index
    victim_image_index = args.image_index
    target_class_index = args.target_class_index
    file_index = args.ip_index
    # Assuming victim_image_index is the index of the image you want to attack
    victim_image = all_data[victim_image_index:victim_image_index+1].to(device)  # Adding batch dimension
    victim_label = labels[victim_image_index]

    outputs = auglag(victim_image)
    probabilities = F.softmax(outputs, dim=1)

    # Get the predicted class and its probability
    predicted_class = probabilities.argmax(dim=1).item()
    predicted_prob = probabilities.max(dim=1).values.item()
    source_class_index = predicted_class
    print(f"Predicted class: {predicted_class} with probability: {predicted_prob}")

    if predicted_class == target_class_index: 
        result_string = "PA_ACC:92.1500 N_flip:0.0000 Diff_Locations:[] Learning Rate:9.999999999999999e-05 Beta:0.5 Top_N:1500"
    
        with open('results_MGDA.txt', 'a') as file:
            file.write(f"attack_idx {victim_image_index}:-:- {result_string}\n")
        return 
    
    # Assuming target_class_index is defined as the index of the class you're interested in
    target_class_prob = probabilities[0, target_class_index].item()

    print(f"Probability of target class ({target_class_index}): {target_class_prob}")
    auglag.to(device)
    
    """Modified GDA on quantized model"""

    learning_rates = [0.5, 0.1, 0.01, 0.001, 0.0001]
    beta_values = [0.5]
    
    best_accuracy = 0
    best_params = {}
    best_nbits = 0
    best_topn = 0
    for lr in learning_rates:
        for beta in beta_values:
            print(f"lr : {lr}, beta: {beta}")
            # Reset model to initial state if necessary
            auglag = AugLag(bit_length, weight, bias, step_size, init=True)
            auglag_ori = copy.deepcopy(auglag)
            auglag.to(device)

            # Run the attack
            top_n, acc_final, n_bit, differing_indices_pairs_2 = M_GDA_Attack(auglag, auglag_ori, device, target_class_index, victim_image, all_data, labels, lr, beta, predicted_class)
            print(f"{victim_image_index} : {acc_final} : {n_bit} : {differing_indices_pairs_2}")

            if(n_bit == 0):
                result_string = "Fail!"
                with open('results_MGDA.txt', 'a') as file:
                    file.write(f"attack_idx {victim_image_index}:-:- {result_string}\n")
                return


            # Evaluate the results
            if acc_final > best_accuracy:
                best_accuracy = acc_final
                best_nbits = n_bit
                best_params = {'learning_rate': lr, 'beta': beta}
                best_differing_indices = differing_indices_pairs_2
                best_topn = top_n

    print("Best Hyperparameters:")
    print("Learning Rate:", best_params['learning_rate'])
    print("Beta:", best_params['beta'])
    print("Accuracy:", best_accuracy)
    

    result_string = "M_GDA: PA_ACC:{0:.4f} N_flip:{1:.4f} Diff_Locations:{2} Learning Rate:{3} Beta:{4} Top_N:{5}".format(
    best_accuracy, best_nbits, best_differing_indices, best_params['learning_rate'], best_params['beta'], best_topn
    )

    print(result_string)
    with open('results_MGDA.txt', 'a') as file:
        file.write(f"attack_idx {victim_image_index}:-:- {result_string}: ip file {file_index}\n")

if __name__ == '__main__':
    main()

