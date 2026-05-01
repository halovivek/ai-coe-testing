"""
Defect Risk Predictor
=====================
ML model that scores defect probability per module to prioritize test effort.
Trained on code metrics, churn history, and historical defect data.

Part of the AI CoE for Testing — halovivek/ai-coe-testing
Author: Vivek Rajagopalan · Senior Director, Engineering
"""

import json
import warnings
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
import joblib

warnings.filterwarnings("ignore")

FEATURE_COLUMNS = [
    "code_churn_lines",          # Lines added+deleted in last 30 days
    "cyclomatic_complexity",     # McCabe complexity score
    "test_coverage_pct",         # Current unit test coverage (0-100)
    "days_since_last_defect",    # Recency of last production defect
    "coupling_score",            # Efferent coupling (deps on other modules)
    "developer_count_30d",       # Unique contributors in last 30 days
    "avg_pr_review_time_hrs",    # Average time PRs sat open before merge
    "open_code_smells",          # SonarQube code smell count
    "critical_path_flag",        # 1 if module is on critical user journey
    "days_since_last_refactor",  # Tech debt indicator
]

RISK_THRESHOLD_HIGH = 0.70
RISK_THRESHOLD_MEDIUM = 0.40


@dataclass
class ModuleMetrics:
    """Input data for a single module risk assessment."""
    module_name: str
    code_churn_lines: int = 0
    cyclomatic_complexity: float = 1.0
    test_coverage_pct: float = 80.0
    days_since_last_defect: int = 365
    coupling_score: int = 3
    developer_count_30d: int = 1
    avg_pr_review_time_hrs: float = 4.0
    open_code_smells: int = 0
    critical_path_flag: int = 0
    days_since_last_refactor: int = 30
    metadata: dict = field(default_factory=dict)


@dataclass
class RiskScore:
    """Output risk assessment for a module."""
    module_name: str
    risk_score: float           # 0.0–1.0
    risk_level: str             # HIGH / MEDIUM / LOW
    top_risk_factors: list
    recommended_actions: list
    estimated_defect_probability: float
    confidence: float


class DefectRiskScorer:
    """
    Gradient Boosting model for module-level defect risk scoring.

    Usage:
        scorer = DefectRiskScorer()
        scorer.train(historical_df)  # Or load pre-trained model
        score = scorer.score_module(module_metrics)
        print(f"{score.module_name}: {score.risk_level} ({score.risk_score:.2f})")
    """

    def __init__(self, model_path: Optional[str] = None):
        self.pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("model", GradientBoostingClassifier(
                n_estimators=200,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                random_state=42
            ))
        ])
        self.feature_importance_ = None
        self.is_trained = False

        if model_path:
            self.load(model_path)

    def train(self, df: pd.DataFrame, target_col: str = "had_defect") -> dict:
        """
        Train the risk model on historical module data.

        Args:
            df: DataFrame with FEATURE_COLUMNS + target_col
            target_col: Binary label — 1 if module had a defect in the period

        Returns:
            Training metrics dict with AUC, precision, recall
        """
        X = df[FEATURE_COLUMNS].fillna(0)
        y = df[target_col]

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )

        self.pipeline.fit(X_train, y_train)
        self.is_trained = True

        # Feature importance (from GBM, post-scaling)
        model = self.pipeline.named_steps["model"]
        self.feature_importance_ = dict(zip(
            FEATURE_COLUMNS,
            model.feature_importances_
        ))

        # Evaluation
        y_pred = self.pipeline.predict(X_test)
        y_prob = self.pipeline.predict_proba(X_test)[:, 1]
        auc = roc_auc_score(y_test, y_prob)
        cv_scores = cross_val_score(self.pipeline, X, y, cv=5, scoring="roc_auc")

        report = classification_report(y_test, y_pred, output_dict=True)
        return {
            "auc_roc": round(auc, 4),
            "cv_auc_mean": round(cv_scores.mean(), 4),
            "cv_auc_std": round(cv_scores.std(), 4),
            "precision": round(report["1"]["precision"], 4),
            "recall": round(report["1"]["recall"], 4),
            "f1": round(report["1"]["f1-score"], 4),
            "top_features": sorted(
                self.feature_importance_.items(),
                key=lambda x: x[1], reverse=True
            )[:5]
        }

    def score_module(self, metrics: ModuleMetrics) -> RiskScore:
        """Score a single module and return a rich risk assessment."""
        if not self.is_trained:
            raise RuntimeError("Model not trained. Call .train() or .load() first.")

        features = pd.DataFrame([{
            col: getattr(metrics, col, 0) for col in FEATURE_COLUMNS
        }])

        prob = self.pipeline.predict_proba(features)[0][1]
        risk_level = (
            "HIGH" if prob >= RISK_THRESHOLD_HIGH else
            "MEDIUM" if prob >= RISK_THRESHOLD_MEDIUM else
            "LOW"
        )

        top_factors = self._identify_risk_factors(metrics, prob)
        actions = self._recommend_actions(risk_level, top_factors, metrics)

        return RiskScore(
            module_name=metrics.module_name,
            risk_score=round(prob, 4),
            risk_level=risk_level,
            top_risk_factors=top_factors,
            recommended_actions=actions,
            estimated_defect_probability=round(prob * 100, 1),
            confidence=0.85  # Can be computed from calibration curve
        )

    def score_portfolio(self, modules: list[ModuleMetrics]) -> pd.DataFrame:
        """Score all modules and return a ranked DataFrame."""
        scores = [self.score_module(m) for m in modules]
        return pd.DataFrame([{
            "module": s.module_name,
            "risk_score": s.risk_score,
            "risk_level": s.risk_level,
            "defect_probability_pct": s.estimated_defect_probability,
            "top_factor": s.top_risk_factors[0] if s.top_risk_factors else "",
            "action": s.recommended_actions[0] if s.recommended_actions else ""
        } for s in scores]).sort_values("risk_score", ascending=False)

    def _identify_risk_factors(
        self, metrics: ModuleMetrics, prob: float
    ) -> list[str]:
        """Identify top contributing risk factors using feature importance."""
        factors = []

        if metrics.code_churn_lines > 500:
            factors.append(f"High code churn ({metrics.code_churn_lines} lines)")
        if metrics.cyclomatic_complexity > 10:
            factors.append(f"Complex code (CC={metrics.cyclomatic_complexity:.0f})")
        if metrics.test_coverage_pct < 60:
            factors.append(f"Low test coverage ({metrics.test_coverage_pct:.0f}%)")
        if metrics.days_since_last_defect < 30:
            factors.append("Recent defect history (< 30 days ago)")
        if metrics.coupling_score > 8:
            factors.append(f"High coupling (score={metrics.coupling_score})")
        if metrics.developer_count_30d > 5:
            factors.append(f"Many contributors ({metrics.developer_count_30d} devs)")
        if metrics.open_code_smells > 20:
            factors.append(f"Code quality issues ({metrics.open_code_smells} smells)")
        if metrics.critical_path_flag:
            factors.append("On critical user journey")

        return factors[:4] or ["Risk profile within normal parameters"]

    def _recommend_actions(
        self, risk_level: str, factors: list[str], metrics: ModuleMetrics
    ) -> list[str]:
        """Generate prioritized testing recommendations."""
        actions = []

        if risk_level == "HIGH":
            actions.append("Prioritize for full regression suite execution")
            actions.append("Assign senior SDET for exploratory testing session")
        elif risk_level == "MEDIUM":
            actions.append("Include in targeted risk-based test cycle")

        if metrics.test_coverage_pct < 60:
            actions.append(
                f"Increase unit test coverage from {metrics.test_coverage_pct:.0f}% to 80%"
            )
        if metrics.code_churn_lines > 500:
            actions.append("Conduct peer code review before release")
        if metrics.cyclomatic_complexity > 10:
            actions.append("Refactor complex functions; add integration tests")
        if metrics.days_since_last_defect < 30:
            actions.append("Re-test all scenarios from last defect fix")

        return actions[:4]

    def save(self, path: str) -> None:
        """Persist trained model to disk."""
        joblib.dump({
            "pipeline": self.pipeline,
            "feature_importance": self.feature_importance_,
            "is_trained": self.is_trained
        }, path)
        print(f"Model saved: {path}")

    def load(self, path: str) -> None:
        """Load a previously saved model."""
        data = joblib.load(path)
        self.pipeline = data["pipeline"]
        self.feature_importance_ = data["feature_importance"]
        self.is_trained = data["is_trained"]


def generate_synthetic_training_data(n_samples: int = 2000) -> pd.DataFrame:
    """Generate synthetic training data for demo/testing."""
    rng = np.random.RandomState(42)

    df = pd.DataFrame({
        "code_churn_lines": rng.exponential(200, n_samples).astype(int),
        "cyclomatic_complexity": rng.exponential(5, n_samples).clip(1, 50),
        "test_coverage_pct": rng.uniform(20, 100, n_samples),
        "days_since_last_defect": rng.exponential(90, n_samples).astype(int),
        "coupling_score": rng.randint(0, 15, n_samples),
        "developer_count_30d": rng.randint(1, 10, n_samples),
        "avg_pr_review_time_hrs": rng.exponential(6, n_samples).clip(0.5, 72),
        "open_code_smells": rng.exponential(10, n_samples).astype(int),
        "critical_path_flag": rng.randint(0, 2, n_samples),
        "days_since_last_refactor": rng.exponential(60, n_samples).astype(int),
    })

    # Create semi-realistic labels based on risk factors
    risk_score = (
        (df["code_churn_lines"] > 400).astype(int) * 0.3 +
        (df["cyclomatic_complexity"] > 10).astype(int) * 0.25 +
        (df["test_coverage_pct"] < 60).astype(int) * 0.20 +
        (df["days_since_last_defect"] < 30).astype(int) * 0.15 +
        (df["coupling_score"] > 8).astype(int) * 0.10
    )
    df["had_defect"] = (risk_score + rng.normal(0, 0.15, n_samples) > 0.35).astype(int)

    return df


if __name__ == "__main__":
    print("=== Defect Risk Predictor Demo ===\n")

    # Train on synthetic data
    print("Generating training data...")
    training_data = generate_synthetic_training_data(2000)

    scorer = DefectRiskScorer()
    print("Training model...")
    metrics = scorer.train(training_data)

    print(f"\nModel performance:")
    print(f"  AUC-ROC: {metrics['auc_roc']} (target: > 0.80)")
    print(f"  CV AUC:  {metrics['cv_auc_mean']} ± {metrics['cv_auc_std']}")
    print(f"  F1:      {metrics['f1']}")
    print(f"\nTop risk features:")
    for feat, importance in metrics["top_features"]:
        print(f"  {feat:<35} {importance:.3f}")

    # Score a portfolio of modules
    test_modules = [
        ModuleMetrics("PaymentGateway", code_churn_lines=850, cyclomatic_complexity=18,
                      test_coverage_pct=45, days_since_last_defect=12, coupling_score=11,
                      developer_count_30d=6, critical_path_flag=1),
        ModuleMetrics("UserAuthService", code_churn_lines=120, cyclomatic_complexity=6,
                      test_coverage_pct=88, days_since_last_defect=180, coupling_score=3,
                      developer_count_30d=2, critical_path_flag=1),
        ModuleMetrics("ReportingModule", code_churn_lines=300, cyclomatic_complexity=9,
                      test_coverage_pct=65, days_since_last_defect=45, coupling_score=5,
                      developer_count_30d=3, open_code_smells=25),
        ModuleMetrics("NotificationService", code_churn_lines=50, cyclomatic_complexity=3,
                      test_coverage_pct=92, days_since_last_defect=365, coupling_score=2,
                      developer_count_30d=1),
    ]

    print("\n=== Module Risk Portfolio ===")
    portfolio = scorer.score_portfolio(test_modules)
    print(portfolio.to_string(index=False))

    print("\n=== Detailed Assessment: PaymentGateway ===")
    gateway_score = scorer.score_module(test_modules[0])
    print(f"Risk Score: {gateway_score.risk_score} ({gateway_score.risk_level})")
    print(f"Defect Probability: {gateway_score.estimated_defect_probability}%")
    print("\nRisk factors:")
    for f in gateway_score.top_risk_factors:
        print(f"  - {f}")
    print("\nRecommended actions:")
    for a in gateway_score.recommended_actions:
        print(f"  → {a}")
