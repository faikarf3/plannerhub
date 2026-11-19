import 'package:firebase_core/firebase_core.dart';
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
  await Firebase.initializeApp(options: DefaultFirebaseOptions.currentPlatform);
  final auth = Auth();
  runApp(PlannerHubApp(auth: auth, api: ApiClient(baseUrl: Config.apiBase, token: auth.token)));
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
