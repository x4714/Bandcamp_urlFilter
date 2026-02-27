import os

files_to_delete = [
    "check_parser.py",
    "test_features.py",
    "test_headless.py",
    "test_parser.py",
    "git_status.tmp",
    "status.txt",
    "test_out.txt",
    "test_out2.txt",
    "parser_out.txt",
    "export_test.txt"
]

for file in files_to_delete:
    if os.path.exists(file):
        try:
            os.remove(file)
            print(f"Deleted {file}")
        except Exception as e:
            print(f"Failed to delete {file}: {e}")
    else:
        print(f"{file} does not exist")
