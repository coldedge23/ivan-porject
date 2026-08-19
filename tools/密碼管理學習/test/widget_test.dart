import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hive/hive.dart';

import 'package:password_manager_learning/screens/home_screen.dart';

void main() {
  setUpAll(() async {
    Hive.init(Directory.systemTemp.path);
    await Hive.openBox('password_entries');
  });

  testWidgets('首頁在沒有資料時顯示空狀態文字', (WidgetTester tester) async {
    await tester.pumpWidget(const MaterialApp(home: HomeScreen()));

    expect(find.text('還沒有任何帳號，點右下角 + 新增'), findsOneWidget);
    expect(find.byIcon(Icons.add), findsOneWidget);
  });
}
