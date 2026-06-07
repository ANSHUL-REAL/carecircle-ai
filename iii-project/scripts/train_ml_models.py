import os
import json
import sys

# Ensure automation folder is in path to import app modules
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(BASE_DIR, 'automation'))

from app.ml_service import train_and_save_models

def main():
    dataset_path = os.path.join(BASE_DIR, 'assets', 'carecircle-dataset.json')
    if not os.path.exists(dataset_path):
        raise FileNotFoundError(f"Dataset not found at {dataset_path}")
        
    with open(dataset_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    print("Retraining models via ml_service...")
    metrics = train_and_save_models(data)
    print("Metrics:")
    print(json.dumps(metrics, indent=2))
    print("Model training successfully completed!")

if __name__ == '__main__':
    main()
