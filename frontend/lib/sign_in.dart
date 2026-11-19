import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';

import 'scope.dart';
import 'theme.dart';

class SignInScreen extends StatefulWidget {
  const SignInScreen({super.key});

  @override
  State<SignInScreen> createState() => _SignInScreenState();
}

class _SignInScreenState extends State<SignInScreen> {
  bool _busy = false;
  String? _error;

  Future<void> _google() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await AppScope.of(context).auth.signInWithGoogle();
    } on FirebaseAuthException catch (e) {
      // Closing the Google window isn't an error worth showing.
      final cancelled = e.code.contains('cancel') || e.code == 'popup-closed-by-user';
      if (mounted && !cancelled) setState(() => _error = e.message ?? 'Sign-in failed (${e.code}).');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 0, 24, 32),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Expanded(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    width: 64, height: 64,
                    decoration: BoxDecoration(color: Palette.red, borderRadius: BorderRadius.circular(18)),
                    child: const Icon(Icons.schedule, color: Colors.white, size: 34),
                  ),
                  const SizedBox(height: 20),
                  const Text('Planner Hub', style: TextStyle(fontSize: 36, fontWeight: FontWeight.w700,
                      letterSpacing: -1)),
                  const SizedBox(height: 10),
                  const Text('Say what you did. See where the time went.',
                      style: TextStyle(fontSize: 17, height: 1.5, color: Color(0xFF52525B))),
                ],
              ),
            ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Text(_error!, textAlign: TextAlign.center,
                    style: const TextStyle(color: Palette.redDark)),
              ),
            SizedBox(
              height: 54,
              child: OutlinedButton(
                onPressed: _busy ? null : _google,
                style: OutlinedButton.styleFrom(
                  foregroundColor: Palette.ink, side: const BorderSide(color: Palette.border),
                  shape: const StadiumBorder(),
                  textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
                child: _busy
                    ? const SizedBox(width: 20, height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2, color: Palette.ink))
                    : const Text('Continue with Google'),
              ),
            ),
            const SizedBox(height: 16),
            const Text('Only your account can open this hub.', textAlign: TextAlign.center,
                style: TextStyle(fontSize: 13, color: Palette.muted)),
          ]),
        ),
      ),
    );
  }
}
