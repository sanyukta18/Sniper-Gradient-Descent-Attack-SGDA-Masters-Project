# Sniper-Gradient-Descent-Attack-SGDA-Masters-Project
Code for Sniper-Gradient Descent Attack (S-GDA) which is an enhanced fault injection technique that refines the effectiveness of the traditional Gradient Descent Attack (GDA) by minimizing parameter changes while guaranteeing accuracy on clean data.

## Steps to run the code : 

1) Download the repository on your system
2) Install the requirements with : pip install -r requirements.txt
3) The script run_script.py reads from cifar_attack_info.txt and runs "search_MGDA.py" with the correct input parameters
(cifar_attack_info.txt has 'target class' and 'attack index'(of image in dataset) as two columns)
4) search_MGDA.py has the main attack script which writes the results to "results_MGDA.txt"
5) In 'results_MGDA.txt' each result entry is like : 
'''
attack_idx 9490:-:- M_GDA: PA_ACC:91.0600 N_flip:2.0000 Diff_Locations:[(0, 58), (0, 60)] Learning Rate:0.5 Beta:0.5 Top_N:1500: ip file 0
'''
where
'''
attack_idx : index of the victim image in dataset. 
PA_ACC : Post Attack accuracy of the model after MGDA attack
N_flip : number of bit flips for MGDA attack success
Diff_Locations : The exact positions in the 2D weight matrix for misclassification 
Learning Rate, Beta, Top_N : Hyperparameters that give optimal PA-accuracy
ip file : Target class to which victim image is mislassified 
'''
