import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/foundation.dart';

import 'config.dart';

/// Who is signed in. With a dev token (frontend/dev.json) the app skips sign-in
/// and uses it for every request; otherwise it signs in with Google through
/// Firebase and sends the Firebase ID token.
class Auth extends ChangeNotifier {
  Auth() {
    if (usingDevToken) {
      ready = true;
    } else {
      FirebaseAuth.instance.authStateChanges().listen((u) {
        user = u;
        ready = true;
        notifyListeners();
      });
    }
  }

  /// Signed in with a fixed token, no Firebase (widget tests).
  Auth.withToken(String token) : _fixedToken = token, ready = true;

  String? _fixedToken;
  bool ready = false;
  User? user;

  bool get usingDevToken => Config.devToken.isNotEmpty;
  bool get signedIn => _fixedToken != null || usingDevToken || user != null;

  /// Why the last sign-in was refused, shown on the sign-in screen.
  String? rejection;

  Future<String?> token({bool refresh = false}) async =>
      _fixedToken ?? (usingDevToken ? Config.devToken : await user?.getIdToken(refresh));

  /// The server refused this account (not allowed, unverified, wrong project…):
  /// sign out and keep its message for the sign-in screen. A dev token can't be
  /// fixed by signing in again, so it's left alone.
  Future<void> rejected(String message) async {
    if (_fixedToken != null || usingDevToken || user == null) return;
    rejection = message;
    await signOut();
  }

  Future<void> signInWithGoogle() async {
    rejection = null;
    final provider = GoogleAuthProvider()..setCustomParameters({'prompt': 'select_account'});
    if (kIsWeb) {
      await FirebaseAuth.instance.signInWithPopup(provider);
    } else {
      await FirebaseAuth.instance.signInWithProvider(provider);
    }
  }

  Future<void> signOut() => FirebaseAuth.instance.signOut();
}
