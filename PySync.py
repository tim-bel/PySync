import os
import sys
import shutil
from pathlib import Path

# --- PyQt6 Imports ---
# We need several components from PyQt6 to build the GUI.
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QLineEdit, QFileDialog, QListWidget, QCheckBox,
    QMessageBox, QTextEdit
)
from PyQt6.QtCore import QThread, QObject, pyqtSignal, Qt

# --- The Core Synchronization Logic ---
# This is the original function, modified to emit signals for GUI updates
# instead of using the logging library.

def sync_folders_for_gui(source_dir: Path, dest_dirs: list[Path], dry_run: bool, progress_emitter: pyqtSignal):
    """
    Synchronizes files and emits progress signals for the GUI.

    Args:
        source_dir (Path): The source directory.
        dest_dirs (list[Path]): A list of destination directories.
        dry_run (bool): If True, simulates the sync.
        progress_emitter (pyqtSignal): The signal to emit log messages to.
    """
    try:
        progress_emitter.emit(f"Starting synchronization for source: '{source_dir}'")
        if dry_run:
            progress_emitter.emit("--- DRY RUN MODE ENABLED: No files will be copied. ---")

        if not source_dir.is_dir():
            progress_emitter.emit(f"Error: Source directory not found at '{source_dir}'")
            return

        for dirpath, _, filenames in os.walk(source_dir):
            for filename in filenames:
                source_file_path = Path(dirpath) / filename
                relative_path = source_file_path.relative_to(source_dir)

                for dest_dir in dest_dirs:
                    dest_file_path = dest_dir / relative_path

                    if not dest_file_path.parent.exists():
                        progress_emitter.emit(f"Creating directory: '{dest_file_path.parent}'")
                        if not dry_run:
                            dest_file_path.parent.mkdir(parents=True, exist_ok=True)

                    should_copy = True
                    if dest_file_path.exists():
                        source_mtime = source_file_path.stat().st_mtime
                        dest_mtime = dest_file_path.stat().st_mtime
                        if source_mtime <= dest_mtime:
                            should_copy = False

                    if should_copy:
                        progress_emitter.emit(f"Copying '{source_file_path.name}' to '{dest_file_path.parent}'")
                        if not dry_run:
                            shutil.copy2(source_file_path, dest_file_path)
                    else:
                        # This log can be noisy, so we'll keep it minimal.
                        # progress_emitter.emit(f"Skipping '{filename}' - already up to date in '{dest_dir}'.")
                        pass

        progress_emitter.emit("Synchronization process completed successfully.")
        if dry_run:
            progress_emitter.emit("--- DRY RUN MODE CONCLUDED ---")

    except Exception as e:
        progress_emitter.emit(f"An unexpected error occurred: {e}")


# --- Worker Thread for Non-Blocking Sync ---
# This class will run the sync operation in a separate thread to keep the GUI responsive.

class SyncWorker(QObject):
    """
    A worker object that performs the synchronization in a separate thread.
    """
    # Signals to communicate with the main GUI thread
    progress = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, source_dir, dest_dirs, dry_run):
        super().__init__()
        self.source_dir = source_dir
        self.dest_dirs = dest_dirs
        self.dry_run = dry_run

    def run(self):
        """Starts the synchronization process."""
        if self.source_dir and self.dest_dirs:
            sync_folders_for_gui(
                self.source_dir,
                self.dest_dirs,
                self.dry_run,
                self.progress
            )
        self.finished.emit()


# --- Main Application Window ---
# This class defines the layout and functionality of the GUI.

class SyncApp(QWidget):
    def __init__(self):
        super().__init__()
        self.source_dir = None
        self.thread = None
        self.worker = None
        self.init_ui()

    def init_ui(self):
        """Sets up the user interface widgets and layouts."""
        self.setWindowTitle('Folder Synchronization Tool')
        self.setGeometry(200, 200, 700, 500)

        # Main vertical layout
        main_layout = QVBoxLayout(self)

        # --- Source Folder Selection ---
        source_layout = QHBoxLayout()
        self.source_label = QLabel("Source Folder:")
        self.source_path_edit = QLineEdit()
        self.source_path_edit.setReadOnly(True)
        self.source_browse_btn = QPushButton("Browse...")
        self.source_browse_btn.clicked.connect(self.select_source_folder)
        source_layout.addWidget(self.source_label)
        source_layout.addWidget(self.source_path_edit)
        source_layout.addWidget(self.source_browse_btn)
        main_layout.addLayout(source_layout)

        # --- Destination Folders Selection ---
        dest_label = QLabel("Destination Folders:")
        main_layout.addWidget(dest_label)
        self.dest_list_widget = QListWidget()
        main_layout.addWidget(self.dest_list_widget)

        dest_buttons_layout = QHBoxLayout()
        self.dest_add_btn = QPushButton("Add Folder")
        self.dest_add_btn.clicked.connect(self.add_destination_folder)
        self.dest_remove_btn = QPushButton("Remove Selected")
        self.dest_remove_btn.clicked.connect(self.remove_destination_folder)
        dest_buttons_layout.addStretch()
        dest_buttons_layout.addWidget(self.dest_add_btn)
        dest_buttons_layout.addWidget(self.dest_remove_btn)
        main_layout.addLayout(dest_buttons_layout)

        # --- Options and Controls ---
        controls_layout = QHBoxLayout()
        self.dry_run_checkbox = QCheckBox("Dry Run (Simulate sync)")
        self.sync_btn = QPushButton("Start Sync")
        self.sync_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px;")
        self.sync_btn.clicked.connect(self.start_sync)
        controls_layout.addWidget(self.dry_run_checkbox)
        controls_layout.addStretch()
        controls_layout.addWidget(self.sync_btn)
        main_layout.addLayout(controls_layout)

        # --- Log Output ---
        log_label = QLabel("Log:")
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        main_layout.addWidget(log_label)
        main_layout.addWidget(self.log_output)

    def select_source_folder(self):
        """Opens a dialog to select the source folder."""
        folder = QFileDialog.getExistingDirectory(self, "Select Source Folder")
        if folder:
            self.source_dir = Path(folder)
            self.source_path_edit.setText(str(self.source_dir))

    def add_destination_folder(self):
        """Opens a dialog to select and add a destination folder."""
        folder = QFileDialog.getExistingDirectory(self, "Select Destination Folder")
        if folder:
            self.dest_list_widget.addItem(folder)

    def remove_destination_folder(self):
        """Removes the currently selected destination folder from the list."""
        selected_items = self.dest_list_widget.selectedItems()
        if not selected_items:
            return
        for item in selected_items:
            self.dest_list_widget.takeItem(self.dest_list_widget.row(item))

    def update_log(self, message):
        """Appends a message to the log display."""
        self.log_output.append(message)

    def set_controls_enabled(self, enabled):
        """Enables or disables UI controls during the sync process."""
        self.source_browse_btn.setEnabled(enabled)
        self.dest_add_btn.setEnabled(enabled)
        self.dest_remove_btn.setEnabled(enabled)
        self.sync_btn.setEnabled(enabled)
        self.dry_run_checkbox.setEnabled(enabled)
        self.sync_btn.setText("Start Sync" if enabled else "Syncing...")

    def start_sync(self):
        """Validates inputs and starts the synchronization thread."""
        if not self.source_dir:
            QMessageBox.warning(self, "Warning", "Please select a source folder.")
            return

        dest_paths = [Path(self.dest_list_widget.item(i).text()) for i in range(self.dest_list_widget.count())]
        if not dest_paths:
            QMessageBox.warning(self, "Warning", "Please add at least one destination folder.")
            return

        self.log_output.clear()
        self.set_controls_enabled(False)

        # --- Set up and start the worker thread ---
        self.thread = QThread()
        self.worker = SyncWorker(self.source_dir, dest_paths, self.dry_run_checkbox.isChecked())
        self.worker.moveToThread(self.thread)

        # Connect signals and slots
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.worker.progress.connect(self.update_log)
        self.thread.finished.connect(self.sync_finished)

        self.thread.start()

    def sync_finished(self):
        """Called when the sync process is complete."""
        self.set_controls_enabled(True)
        QMessageBox.information(self, "Success", "Synchronization process has finished.")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SyncApp()
    window.show()
    sys.exit(app.exec())
