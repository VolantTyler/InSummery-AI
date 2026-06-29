# Project-Scoped Rules & Preferences

## Firebase Setup and Emulators
- **Prerequisite**: The web application relies on the Firebase Emulator Suite (Firestore, Functions, Hosting, Auth) for local development.
- **Global Installation**: Always ensure the Firebase CLI is installed globally. If `firebase` is not recognized, run:
  ```bash
  npm install -g firebase-tools
  firebase login
  ```
- **Starting Emulators**: Use `firebase emulators:start` to run the backend and hosting locally.
