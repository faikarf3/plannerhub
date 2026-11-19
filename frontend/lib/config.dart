/// Build-time settings, passed with --dart-define or --dart-define-from-file.
abstract final class Config {
  static const apiBase = String.fromEnvironment(
    'PLANNER_API',
    defaultValue: 'https://planner-api-885606868208.us-east4.run.app',
  );

  /// The backend's owner token, for development until the backend accepts
  /// Firebase sign-in. Never committed: put it in frontend/dev.json (gitignored).
  static const devToken = String.fromEnvironment('PLANNER_TOKEN');
}
