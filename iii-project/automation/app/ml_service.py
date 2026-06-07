import os
import json
import torch
import torch.nn as nn
import torch.optim as optim
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, mean_absolute_error, accuracy_score

# Resolve paths
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(CURRENT_DIR)), 'assets')

PATIENT_MODEL_PATH = os.path.join(ASSETS_DIR, 'patient_cycle_model.pt')
DONOR_MODEL_PATH = os.path.join(ASSETS_DIR, 'donor_active_model.pt')
METRICS_PATH = os.path.join(ASSETS_DIR, 'model_evaluation_metrics.json')

# --- PyTorch Model Architecture Definitions ---
class PatientRegressorNN(nn.Module):
    def __init__(self, input_dim):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 32),
            nn.ReLU(),
            nn.Linear(32, 16),
            nn.ReLU(),
            nn.Linear(16, 1)
        )
    def forward(self, x):
        return self.net(x)

class DonorClassifierNN(nn.Module):
    def __init__(self, input_dim):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 32),
            nn.ReLU(),
            nn.Linear(32, 16),
            nn.ReLU(),
            nn.Linear(16, 1)
        )
    def forward(self, x):
        return torch.sigmoid(self.net(x))

# --- Cache variables ---
_patient_metadata = None
_patient_model = None
_donor_metadata = None
_donor_model = None

def _load_patient_model(force_reload=False):
    global _patient_metadata, _patient_model
    if _patient_model is None or force_reload:
        if not os.path.exists(PATIENT_MODEL_PATH):
            return None
        try:
            _patient_metadata = torch.load(PATIENT_MODEL_PATH, weights_only=False)
            _patient_model = PatientRegressorNN(_patient_metadata['input_dim'])
            _patient_model.load_state_dict(_patient_metadata['state_dict'])
            _patient_model.eval()
        except Exception:
            return None
    return _patient_model

def _load_donor_model(force_reload=False):
    global _donor_metadata, _donor_model
    if _donor_model is None or force_reload:
        if not os.path.exists(DONOR_MODEL_PATH):
            return None
        try:
            _donor_metadata = torch.load(DONOR_MODEL_PATH, weights_only=False)
            _donor_model = DonorClassifierNN(_donor_metadata['input_dim'])
            _donor_model.load_state_dict(_donor_metadata['state_dict'])
            _donor_model.eval()
        except Exception:
            return None
    return _donor_model

def predict_patient_frequency(condition: str, gender: str, quantity_required: int) -> float:
    """
    Predicts the transfusion frequency cycle in days for a patient using PyTorch.
    Falls back to deterministic heuristics if the model is not trained.
    """
    model = _load_patient_model()
    if model is None or _patient_metadata is None:
        cond_lower = condition.lower()
        if "major" in cond_lower:
            return 14.0
        if "sickle" in cond_lower:
            return 21.0
        return 25.0

    feature_names = _patient_metadata['feature_names']
    input_data = {
        'condition': [condition],
        'gender': [gender],
        'quantity_required': [quantity_required]
    }
    df_input = pd.DataFrame(input_data)
    df_encoded = pd.get_dummies(df_input, columns=['condition', 'gender'])
    df_aligned = df_encoded.reindex(columns=feature_names, fill_value=0).astype(np.float32)
    
    tensor_input = torch.tensor(df_aligned.values)
    with torch.no_grad():
        prediction = model(tensor_input).item()
    return float(prediction)

def predict_donor_active_status(
    gender: str,
    donor_type: str,
    donations_till_date: int,
    total_calls: int,
    cycle_of_donations: int
) -> bool:
    """
    Predicts if a donor is Active (True) or Inactive (False) based on profile data using PyTorch.
    Falls back to heuristics if the model is not trained.
    """
    model = _load_donor_model()
    if model is None or _donor_metadata is None:
        return donations_till_date > 0 or total_calls < 5

    feature_names = _donor_metadata['feature_names']
    input_data = {
        'gender': [gender],
        'donor_type': [donor_type],
        'donations_till_date': [donations_till_date],
        'total_calls': [total_calls],
        'cycle_of_donations': [cycle_of_donations]
    }
    df_input = pd.DataFrame(input_data)
    df_encoded = pd.get_dummies(df_input, columns=['gender', 'donor_type'])
    df_aligned = df_encoded.reindex(columns=feature_names, fill_value=0).astype(np.float32)
    
    tensor_input = torch.tensor(df_aligned.values)
    with torch.no_grad():
        probability = model(tensor_input).item()
    return bool(probability > 0.5)

def train_and_save_models(data: dict) -> dict:
    """
    Retrains the PyTorch patient cycle regressor and donor active status classifier on-the-fly.
    Saves serialized state dicts and returns evaluation metrics.
    """
    # 1. Train Patient Cycle Model (Regression)
    patients = data.get('patients', [])
    df_p = pd.DataFrame(patients)
    
    # Defensive column setup
    for col in ['gender', 'condition', 'blood_group']:
        if col not in df_p.columns:
            df_p[col] = 'Unknown'
        else:
            df_p[col] = df_p[col].fillna('Unknown')
            
    if 'quantity_required' not in df_p.columns:
        df_p['quantity_required'] = 1
    else:
        df_p['quantity_required'] = df_p['quantity_required'].fillna(1)
        
    if 'frequency_days' not in df_p.columns:
        df_p['frequency_days'] = 21
    else:
        df_p['frequency_days'] = df_p['frequency_days'].fillna(21)
    
    X_p = df_p[['condition', 'gender', 'blood_group', 'quantity_required']]
    y_p = df_p['frequency_days']
    X_p_encoded = pd.get_dummies(X_p, columns=['condition', 'gender', 'blood_group'])
    feature_names_p = X_p_encoded.columns.tolist()
    
    X_train_p, X_test_p, y_train_p, y_test_p = train_test_split(
        X_p_encoded.astype(np.float32), y_p.astype(np.float32), test_size=0.2, random_state=42
    )
    
    X_train_pt = torch.tensor(X_train_p.values)
    y_train_pt = torch.tensor(y_train_p.values).unsqueeze(1)
    X_test_pt = torch.tensor(X_test_p.values)
    y_test_pt = torch.tensor(y_test_p.values).unsqueeze(1)
    
    model_p = PatientRegressorNN(len(feature_names_p))
    criterion_p = nn.MSELoss()
    optimizer_p = optim.Adam(model_p.parameters(), lr=0.005)
    
    # Train regressor thoroughly (250 epochs)
    for epoch in range(250):
        model_p.train()
        optimizer_p.zero_grad()
        preds = model_p(X_train_pt)
        loss = criterion_p(preds, y_train_pt)
        loss.backward()
        optimizer_p.step()
        
    model_p.eval()
    with torch.no_grad():
        test_preds_p = model_p(X_test_pt)
        test_mse = criterion_p(test_preds_p, y_test_pt).item()
        test_mae = torch.mean(torch.abs(test_preds_p - y_test_pt)).item()
        
    patient_metadata = {
        'state_dict': model_p.state_dict(),
        'input_dim': len(feature_names_p),
        'feature_names': feature_names_p,
        'categorical_columns': ['condition', 'gender', 'blood_group']
    }
    torch.save(patient_metadata, PATIENT_MODEL_PATH)
    
    patient_metrics = {
        "MAE": float(test_mae),
        "MSE": float(test_mse)
    }
    
    # 2. Train Donor Active Model (Classification)
    donors = data.get('donors', [])
    df_d = pd.DataFrame(donors)
    
    # Defensive column setup
    for col in ['gender', 'donor_type', 'blood_group']:
        if col not in df_d.columns:
            df_d[col] = 'Unknown'
        else:
            df_d[col] = df_d[col].fillna('Unknown')
            
    for col in ['donations_till_date', 'total_calls']:
        if col not in df_d.columns:
            df_d[col] = 0
        else:
            df_d[col] = df_d[col].fillna(0)
            
    if 'cycle_of_donations' not in df_d.columns:
        df_d['cycle_of_donations'] = 90
    else:
        df_d['cycle_of_donations'] = df_d['cycle_of_donations'].fillna(90)
    
    if 'active_status' in df_d.columns:
        df_d['is_active'] = (df_d['active_status'].str.lower() == 'active').astype(int)
    else:
        df_d['is_active'] = 1
        
    X_d = df_d[['gender', 'donor_type', 'blood_group', 'donations_till_date', 'total_calls', 'cycle_of_donations']]
    y_d = df_d['is_active']
    X_d_encoded = pd.get_dummies(X_d, columns=['gender', 'donor_type', 'blood_group'])
    feature_names_d = X_d_encoded.columns.tolist()
    
    X_train_d, X_test_d, y_train_d, y_test_d = train_test_split(
        X_d_encoded.astype(np.float32), y_d.astype(np.float32), test_size=0.2, random_state=42
    )
    
    X_train_dt = torch.tensor(X_train_d.values)
    y_train_dt = torch.tensor(y_train_d.values).unsqueeze(1)
    X_test_dt = torch.tensor(X_test_d.values)
    y_test_dt = torch.tensor(y_test_d.values).unsqueeze(1)
    
    model_d = DonorClassifierNN(len(feature_names_d))
    criterion_d = nn.BCELoss()
    optimizer_d = optim.Adam(model_d.parameters(), lr=0.005)
    
    # Train classifier thoroughly (200 epochs)
    for epoch in range(200):
        model_d.train()
        optimizer_d.zero_grad()
        preds = model_d(X_train_dt)
        loss = criterion_d(preds, y_train_dt)
        loss.backward()
        optimizer_d.step()
        
    model_d.eval()
    with torch.no_grad():
        test_preds_d = model_d(X_test_dt)
        binary_preds = (test_preds_d > 0.5).float()
        test_accuracy = (binary_preds == y_test_dt).float().mean().item()
        
    donor_metadata = {
        'state_dict': model_d.state_dict(),
        'input_dim': len(feature_names_d),
        'feature_names': feature_names_d,
        'categorical_columns': ['gender', 'donor_type', 'blood_group']
    }
    torch.save(donor_metadata, DONOR_MODEL_PATH)
    
    donor_metrics = {
        "Accuracy": float(test_accuracy)
    }
    
    # Save consolidated metrics
    metrics = {
        "patient_cycle_model": patient_metrics,
        "donor_active_model": donor_metrics,
        "trained_at": pd.Timestamp.now().isoformat(),
        "framework": "pytorch"
    }
    with open(METRICS_PATH, 'w') as f:
        json.dump(metrics, f, indent=2)
        
    # Force reload of cached models
    _load_patient_model(force_reload=True)
    _load_donor_model(force_reload=True)
    
    return metrics
