import os
import json
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class StorageProvider(ABC):
    @abstractmethod
    def get_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve the family profile for a user."""
        pass

    @abstractmethod
    def save_profile(self, user_id: str, profile: Dict[str, Any]) -> None:
        """Save the family profile for a user."""
        pass

    @abstractmethod
    def get_matrix(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve the schedule matrix for a user."""
        pass

    @abstractmethod
    def save_matrix(self, user_id: str, matrix: Dict[str, Any]) -> None:
        """Save the schedule matrix for a user."""
        pass

    @abstractmethod
    def get_pending_workflow(self, user_id: str, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a paused workflow state by ID."""
        pass

    @abstractmethod
    def save_pending_workflow(self, user_id: str, workflow_id: str, state: Dict[str, Any]) -> None:
        """Save a paused workflow state."""
        pass


class LocalStorageProvider(StorageProvider):
    def __init__(self, base_dir: str = "."):
        self.base_dir = base_dir
        self.config_dir = os.path.join(base_dir, "config")
        self.data_dir = os.path.join(base_dir, "data")
        
        # Ensure directories exist
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(self.data_dir, exist_ok=True)

    def _get_profile_path(self) -> str:
        return os.path.join(self.config_dir, "profile.json")

    def _get_matrix_path(self) -> str:
        return os.path.join(self.data_dir, "matrix.json")

    def _get_pending_workflows_path(self) -> str:
        return os.path.join(self.data_dir, "pending_workflows.json")

    def get_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        path = self._get_profile_path()
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def save_profile(self, user_id: str, profile: Dict[str, Any]) -> None:
        path = self._get_profile_path()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(profile, f, indent=2, ensure_ascii=False)

    def get_matrix(self, user_id: str) -> Optional[Dict[str, Any]]:
        path = self._get_matrix_path()
        if not os.path.exists(path):
            return {"activities": [], "gaps": []}
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def save_matrix(self, user_id: str, matrix: Dict[str, Any]) -> None:
        path = self._get_matrix_path()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(matrix, f, indent=2, ensure_ascii=False)

    def get_pending_workflow(self, user_id: str, workflow_id: str) -> Optional[Dict[str, Any]]:
        path = self._get_pending_workflows_path()
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            workflows = json.load(f)
        return workflows.get(f"{user_id}#{workflow_id}")

    def save_pending_workflow(self, user_id: str, workflow_id: str, state: Dict[str, Any]) -> None:
        path = self._get_pending_workflows_path()
        workflows = {}
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    workflows = json.load(f)
            except json.JSONDecodeError:
                pass
        
        workflows[f"{user_id}#{workflow_id}"] = state
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(workflows, f, indent=2, ensure_ascii=False)


class FirestoreStorageProvider(StorageProvider):
    def __init__(self):
        # We import firebase_admin here to avoid requiring it in purely local mode
        import firebase_admin
        from firebase_admin import firestore
        
        # Initialize firebase_admin if not already initialized
        try:
            self.db = firestore.client()
        except ValueError:
            firebase_admin.initialize_app()
            self.db = firestore.client()

    def get_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        doc_ref = self.db.collection("users").document(user_id).collection("config").document("profile")
        doc = doc_ref.get()
        return doc.to_dict() if doc.exists else None

    def save_profile(self, user_id: str, profile: Dict[str, Any]) -> None:
        doc_ref = self.db.collection("users").document(user_id).collection("config").document("profile")
        doc_ref.set(profile)

    def get_matrix(self, user_id: str) -> Optional[Dict[str, Any]]:
        doc_ref = self.db.collection("users").document(user_id).collection("data").document("matrix")
        doc = doc_ref.get()
        return doc.to_dict() if doc.exists else {"activities": [], "gaps": []}

    def save_matrix(self, user_id: str, matrix: Dict[str, Any]) -> None:
        doc_ref = self.db.collection("users").document(user_id).collection("data").document("matrix")
        doc_ref.set(matrix)

    def get_pending_workflow(self, user_id: str, workflow_id: str) -> Optional[Dict[str, Any]]:
        doc_ref = self.db.collection("users").document(user_id).collection("pending_workflows").document(workflow_id)
        doc = doc_ref.get()
        return doc.to_dict() if doc.exists else None

    def save_pending_workflow(self, user_id: str, workflow_id: str, state: Dict[str, Any]) -> None:
        doc_ref = self.db.collection("users").document(user_id).collection("pending_workflows").document(workflow_id)
        doc_ref.set(state)
