// Firebase app identifiers (not secrets). Written from the Firebase Management API
// for project planner-hub-97a70d; equivalent to `flutterfire configure` output.
// ignore_for_file: type=lint
import 'package:firebase_core/firebase_core.dart' show FirebaseOptions;
import 'package:flutter/foundation.dart' show defaultTargetPlatform, kIsWeb, TargetPlatform;

class DefaultFirebaseOptions {
  static FirebaseOptions get currentPlatform {
    if (kIsWeb) return web;
    if (defaultTargetPlatform == TargetPlatform.iOS) return ios;
    throw UnsupportedError('Planner Hub is built for iOS and web only.');
  }

  static const FirebaseOptions web = FirebaseOptions(
    apiKey: 'AIzaSyBmrGfkeaIt-G2pWuMey3hZkuD7b3kWwBI',
    appId: '1:885606868208:web:0d0965748f8353915e8e35',
    messagingSenderId: '885606868208',
    projectId: 'planner-hub-97a70d',
    authDomain: 'planner-hub-97a70d.firebaseapp.com',
    storageBucket: 'planner-hub-97a70d.firebasestorage.app',
  );

  static const FirebaseOptions ios = FirebaseOptions(
    apiKey: 'AIzaSyCfJru5w9Rrzzza3qXd-SmeNv6eglZv8Ts',
    appId: '1:885606868208:ios:8eb5de380cdb24cc5e8e35',
    messagingSenderId: '885606868208',
    projectId: 'planner-hub-97a70d',
    storageBucket: 'planner-hub-97a70d.firebasestorage.app',
    iosBundleId: 'com.plannerhub.plannerHub',
  );
}
