import json
import subprocess
import numpy as np

# Path to the script that processes a specific image
script_path = 'search_MGDA.py'

attack_info = np.loadtxt("cifar_attack_info.txt").astype(int)
for i, (target_class, attack_idx) in enumerate(attack_info):
    print(f"Starting processing for image index {attack_idx}")
    subprocess.run(['python3', script_path, '--image_index', str(attack_idx),'--target_class_index', str(target_class), '--ip_index',str(0)], check=True)
    print(f"Completed processing for image index {attack_idx}")

