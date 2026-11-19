import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';

import 'api/client.dart';
import 'auth.dart';
import 'config.dart';
import 'firebase_options.dart';
import 'scope.dart';
import 'shell.dart';
import 'sign_in.dart';
import 'theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp(options: _firebaseOptions());
  final auth = Auth();
  final api = ApiClient(baseUrl: Config.apiBase, token: auth.token, onUnauthorized: auth.rejected);
  runApp(PlannerHubApp(auth: auth, api: api));
}

/// On the published site, sign-in returns through the site's own /__/auth/handler
/// (served by Firebase Hosting). Safari blocks the redirect flow when that
/// handler is on another domain. Everywhere else, the default auth domain.
FirebaseOptions _firebaseOptions() {
  final host = Uri.base.host;
  if (kIsWeb && (host.endsWith('.web.app') || host.endsWith('.firebaseapp.com'))) {
    return DefaultFirebaseOptions.web.copyWith(authDomain: host);
  }
  return DefaultFirebaseOptions.currentPlatform;
}

class PlannerHubApp extends StatelessWidget {
  const PlannerHubApp({super.key, required this.auth, required this.api});
  final Auth auth;
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return AppScope(
      api: api,
      auth: auth,
      child: MaterialApp(
        title: 'Planner Hub',
        debugShowCheckedModeBanner: false,
        theme: buildTheme(),
        home: ListenableBuilder(
          listenable: auth,
          builder: (context, _) {
            if (!auth.ready) return const Scaffold();
            return auth.signedIn ? const Shell() : const SignInScreen();
          },
        ),
      ),
    );
  }
}
