⚡ String Contester
A simple, fast desktop application for running school programming contests, lab work, and exams in computer science.

It was built with a straightforward goal: create a testing tool that doesn't lag, doesn't require setting up complex servers, and works right off a USB drive or inside a local school lab.

The project consists of two separate apps: teacher.exe (for the instructor) and student.exe (for the student).

🚀 How It Works
The entire contest state revolves around a single file: tasks.json.

The teacher opens teacher.exe, creates problems, attaches screenshots of the task conditions, and pastes test sets. Clicking "Save" generates a tasks.json file.

The tasks.json file is copied to a USB drive or distributed across student PCs into the same folder as student.exe.

Students launch student.exe, write their code, run tests, and export their final results.

🛠 Complete Feature Breakdown
👨‍🏫 Teacher Panel (teacher.exe):
Up to 5 tasks per contest: Ideal for a single class session, lab work, or an olympiad round.

Task screenshots: Attach images (PNG, JPG) containing problem descriptions directly into the contest payload.

Easy test suite setup: Input and expected output values are pasted in a simple block using --- as a delimiter. You can add 20–30 test cases in seconds.

Feature bans: Easily disable specific code features with checkboxes (if, while, for, lambda, or def/void) for tasks that target specific concepts like math formulas or recursion.

Custom scoring: Assign custom maximum point values per task.

👨‍🎓 Student Environment (student.exe):
Side-by-side view: The UI is split down the middle. The task screenshot stays pinned on the left side, while the right side houses the code editor and test console.

Multi-language support: Students can solve problems in Python, C++, or JavaScript (Node.js).

Fast execution engine:

Python: Code executes directly inside the process memory without dumping temporary files to disk. Instant checks, no lag, and no stream redirection crashes (stderr).

C++ & JS: Compiled/run safely via sub-processes with piped stdin data and strict timeouts to prevent infinite loops from hanging the PC.

Anti-cheat window control: The app window cannot be minimized to the taskbar (if minimized, it instantly pops back up). However, students can freely close the window using the standard "X" button once done (no annoying exit passwords).

Visual feedback: Once a task passes all test cases, the interface highlights green and marks the task with a checkmark in the list.

Submission reports: At the end, students fill in their Name and Group, click "Submit All Works", and get a clean .txt report containing their total score, test result logs, and full source code for every problem.

📋 Requirements
To run pre-built .exe files: Windows OS.

For Python testing: Built-in runtime (no external packages needed).

For C++ testing: A g++ compiler (MinGW) must be installed and added to system PATH.

For JavaScript testing: Node.js installed on the host system.

👨‍💻 Running from Source
If you want to run or modify the project using raw Python files:

Bash
# Run Teacher App
python teacher.py

# Run Student App (requires tasks.json in the same folder)
python student.py
Optional dependency for extended image handling: pip install pillow

📦 Building .exe Binaries
To recompile .exe files using PyInstaller:

DOS
# Build Teacher binary
python -m PyInstaller --onefile --windowed --name Teacher teacher.py

# Build Student binary
python -m PyInstaller --onefile --windowed --name Student student.py
The output executables will be generated inside the dist/ directory.
