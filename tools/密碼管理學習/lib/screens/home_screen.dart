import 'package:flutter/material.dart';

import '../models/password_entry.dart';
import '../services/crypto_service.dart';
import '../services/entry_storage.dart';
import 'edit_entry_screen.dart';
import 'unlock_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  List<PasswordEntry> _entries = [];

  @override
  void initState() {
    super.initState();
    _loadEntries();
  }

  void _loadEntries() {
    setState(() => _entries = EntryStorage.getAll());
  }

  Future<void> _openAddScreen() async {
    final newEntry = await Navigator.of(context).push<PasswordEntry>(
      MaterialPageRoute(builder: (_) => const EditEntryScreen()),
    );
    if (newEntry != null) {
      await EntryStorage.save(newEntry);
      _loadEntries();
    }
  }

  Future<void> _openEditScreen(PasswordEntry entry) async {
    final updatedEntry = await Navigator.of(context).push<PasswordEntry>(
      MaterialPageRoute(builder: (_) => EditEntryScreen(existingEntry: entry)),
    );
    if (updatedEntry != null) {
      await EntryStorage.save(updatedEntry);
      _loadEntries();
    }
  }

  Future<void> _deleteEntry(PasswordEntry entry) async {
    await EntryStorage.delete(entry.id);
    _loadEntries();
  }

  void _lock() {
    CryptoService.lock();
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => const UnlockScreen()),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('我的帳號密碼（學習版）'),
        actions: [
          IconButton(
            icon: const Icon(Icons.lock_outline),
            tooltip: '鎖定',
            onPressed: _lock,
          ),
        ],
      ),
      body: _entries.isEmpty
          ? const Center(child: Text('還沒有任何帳號，點右下角 + 新增'))
          : ListView.builder(
              itemCount: _entries.length,
              itemBuilder: (context, index) {
                final entry = _entries[index];
                return Dismissible(
                  key: ValueKey(entry.id),
                  direction: DismissDirection.endToStart,
                  background: Container(
                    color: Colors.red,
                    alignment: Alignment.centerRight,
                    padding: const EdgeInsets.symmetric(horizontal: 20),
                    child: const Icon(Icons.delete, color: Colors.white),
                  ),
                  onDismissed: (_) => _deleteEntry(entry),
                  child: ListTile(
                    title: Text(entry.title),
                    subtitle: Text(entry.username),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => _openEditScreen(entry),
                  ),
                );
              },
            ),
      floatingActionButton: FloatingActionButton(
        onPressed: _openAddScreen,
        tooltip: '新增帳號',
        child: const Icon(Icons.add),
      ),
    );
  }
}
