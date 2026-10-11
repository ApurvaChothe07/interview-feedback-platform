#!/usr/bin/env python3
"""
Train an XGBoost regression model to predict candidate interview delivery score
using multimodal features (audio-to-text / speech, gaze, facial dynamics, and acoustics).

Saves:
- models/delivery_xgboost.joblib
- models/feature_columns.json
- models/training_report.json
"""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold, cross_val_score, train_test_split
import xgboost as xgb


def train_model(features_csv="dataset_features.csv", models_dir="models"):
    print(f"Loading features from {features_csv}...")
    df = pd.read_csv(features_csv)
    print(f"Loaded {len(df)} sessions.")

    # Target variable
    target_col = "delivery_overall"
    if target_col not in df.columns:
        raise ValueError(f"Target column '{target_col}' not found in {features_csv}")

    # Exclude non-feature columns
    exclude = {"session_id", "delivery_overall", "Participant_ID", "PHQ8_Score", "PHQ8_Binary"}
    feature_cols = [c for c in df.columns if c not in exclude]

    X = df[feature_cols].copy()
    y = df[target_col].copy()

    print(f"Number of input features: {len(feature_cols)}")
    print(f"Features: {feature_cols}")

    # Split train/test (80/20)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42
    )
    print(f"Training set: {len(X_train)} samples, Test set: {len(X_test)} samples.")

    # Configure XGBoost regressor
    # Note: XGBoost natively supports missing values (np.nan), which is ideal
    # for real-time inference when live gaze or audio features might be optional.
    model = xgb.XGBRegressor(
        n_estimators=150,
        learning_rate=0.04,
        max_depth=4,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_alpha=0.1,
        reg_lambda=1.0,
        random_state=42,
        objective="reg:squarederror",
    )

    # 5-fold cross validation
    cv = KFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = cross_val_score(model, X_train, y_train, cv=cv, scoring="neg_mean_absolute_error")
    cv_mae = -cv_scores.mean()

    # Train final model on training set
    model.fit(X_train, y_train)

    # Predictions
    y_pred_train = model.predict(X_train)
    y_pred_test = model.predict(X_test)

    train_mae = mean_absolute_error(y_train, y_pred_train)
    train_rmse = np.sqrt(mean_squared_error(y_train, y_pred_train))
    train_r2 = r2_score(y_train, y_pred_train)

    test_mae = mean_absolute_error(y_test, y_pred_test)
    test_rmse = np.sqrt(mean_squared_error(y_test, y_pred_test))
    test_r2 = r2_score(y_test, y_pred_test)

    print("\n--- Model Performance Evaluation ---")
    print(f"5-Fold CV MAE:     {cv_mae:.2f} points")
    print(f"Train MAE:         {train_mae:.2f} points | RMSE: {train_rmse:.2f} | R2: {train_r2:.3f}")
    print(f"Test MAE:          {test_mae:.2f} points | RMSE: {test_rmse:.2f} | R2: {test_r2:.3f}")

    # Feature Importance
    importances = model.feature_importances_
    feat_imp = sorted(zip(feature_cols, importances), key=lambda x: x[1], reverse=True)
    print("\n--- Top 10 Most Influential Features ---")
    for feat, imp in feat_imp[:10]:
        print(f"  {feat:<26}: {imp*100:.1f}%")

    # Save artifacts
    out_dir = Path(models_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    model_path = out_dir / "delivery_xgboost.joblib"
    cols_path = out_dir / "feature_columns.json"
    report_path = out_dir / "training_report.json"

    joblib.dump(model, model_path)
    cols_path.write_text(json.dumps(feature_cols, indent=2))

    summary = {
        "model_type": "XGBoost Regressor (xgb.XGBRegressor)",
        "features_count": len(feature_cols),
        "dataset_rows": len(df),
        "train_rows": len(X_train),
        "test_rows": len(X_test),
        "metrics": {
            "cv_mae": round(float(cv_mae), 3),
            "train_mae": round(float(train_mae), 3),
            "train_rmse": round(float(train_rmse), 3),
            "train_r2": round(float(train_r2), 3),
            "test_mae": round(float(test_mae), 3),
            "test_rmse": round(float(test_rmse), 3),
            "test_r2": round(float(test_r2), 3),
        },
        "feature_importances": {feat: round(float(imp), 4) for feat, imp in feat_imp},
    }
    report_path.write_text(json.dumps(summary, indent=2))

    print(f"\nSaved trained model to: {model_path.resolve()}")
    print(f"Saved feature list to:   {cols_path.resolve()}")
    print(f"Saved training report to: {report_path.resolve()}")


if __name__ == "__main__":
    train_model()
