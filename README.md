# Sniper-Gradient-Descent-Attack-SGDA-Masters-Project
Code for Sniper-Gradient Descent Attack (S-GDA), an enhanced fault injection technique that refines the effectiveness of the traditional Gradient Descent Attack (GDA) by minimizing parameter changes while guaranteeing accuracy on clean data.

## Steps to run the code : 

1) Download the repository on your system
2) Install the requirements with :
 ```
pip install -r requirements.txt
```
4) The script run_script.py reads from cifar_attack_info.txt and runs "search_MGDA.py" with the correct input parameters with :
```
python3 run_script.py
```   
(cifar_attack_info.txt has 'target class' and 'attack index' as two columns)

5) 'search_MGDA.py' is the main attack script which writes the results to "results_MGDA.txt"
7) In 'results_MGDA.txt' each result entry is like this:
```   
attack_idx 9490:-:- M_GDA: PA_ACC:91.0600 N_flip:2.0000 Diff_Locations:[(0, 58), (0, 60)] Learning Rate:0.5 Beta:0.5 Top_N:1500: ip file 0
```
where
```
attack_idx: index of the victim image in the dataset. 
PA_ACC: Post Attack accuracy of the model after MGDA attack
N_flip: Number of bit flips for MGDA attack success
Diff_Locations: The positions in the 2D weight matrix for misclassification 
Learning Rate, Beta, Top_N : Hyperparameters that give optimal PA-accuracy
ip file: Target class to which victim image is misclassified 
```
Note: To parallelize the process of attack on 1000 images in 'cifar_attack_info.txt' multiple similar files can be made by dividing the 1000 entries in it. From 'cifar_attack_info.txt' make 'cifar_attack_info1.txt', 'cifar_attack_info2.txt' and so on. Multiple run_script.py files can be made for each like 'run_script_1.py', 'run_script_2.py' so on.
