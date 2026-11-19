import 'package:flutter/widgets.dart';

import 'api/client.dart';
import 'auth.dart';

/// Makes the API client and auth available below it.
class AppScope extends InheritedWidget {
  const AppScope({super.key, required this.api, required this.auth, required super.child});

  final ApiClient api;
  final Auth auth;

  static AppScope of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<AppScope>()!;

  @override
  bool updateShouldNotify(AppScope old) => api != old.api || auth != old.auth;
}
