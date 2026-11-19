import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// White, near-black text, red only as an accent (see the design canvas).
abstract final class Palette {
  static const ink = Color(0xFF18181B);
  static const body = Color(0xFF3F3F46);
  static const muted = Color(0xFF6B6B73);
  static const faint = Color(0xFFA1A1AA);
  static const line = Color(0xFFF0F0F0);
  static const border = Color(0xFFE4E4E7);
  static const field = Color(0xFFFAFAFA);
  static const grey = Color(0xFFF4F4F5);
  static const check = Color(0xFFC9C9CF);
  static const red = Color(0xFFD92D20);
  static const redDark = Color(0xFFB42318);
  static const redDeep = Color(0xFF912018);
  static const redTint = Color(0xFFFEF3F2);
  static const redBorder = Color(0xFFF3C9C5);
}

/// `fonts: false` skips downloading Inter (tests run offline).
ThemeData buildTheme({bool fonts = true}) {
  final family = fonts ? GoogleFonts.inter().fontFamily : null;
  final text = ThemeData.light().textTheme.apply(
    fontFamily: family,
    bodyColor: Palette.ink,
    displayColor: Palette.ink,
  );
  return ThemeData(
    useMaterial3: true,
    fontFamily: family,
    colorScheme: const ColorScheme.light(
      primary: Palette.red,
      onPrimary: Colors.white,
      surface: Colors.white,
      onSurface: Palette.ink,
      error: Palette.redDark,
    ),
    scaffoldBackgroundColor: Colors.white,
    textTheme: text,
    splashFactory: NoSplash.splashFactory,
    snackBarTheme: SnackBarThemeData(
      backgroundColor: Palette.ink,
      contentTextStyle: TextStyle(fontFamily: family, color: Colors.white, fontSize: 14),
      actionTextColor: const Color(0xFFFCA5A5),
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Palette.field,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      hintStyle: TextStyle(fontFamily: family, color: Palette.muted, fontSize: 16),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(24),
        borderSide: const BorderSide(color: Palette.border),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(24),
        borderSide: const BorderSide(color: Palette.border),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(24),
        borderSide: const BorderSide(color: Palette.faint),
      ),
    ),
    bottomSheetTheme: const BottomSheetThemeData(
      backgroundColor: Colors.white,
      surfaceTintColor: Colors.white,
      showDragHandle: true,
      dragHandleColor: Palette.border,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(28))),
    ),
  );
}

/// Section labels: small, grey, uppercase ("DUE", "LOGGED").
TextStyle sectionLabel() => const TextStyle(
      fontSize: 13,
      fontWeight: FontWeight.w600,
      color: Palette.muted,
      letterSpacing: 0.8,
    );
