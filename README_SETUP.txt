DTALite Pipeline Windows Setup and Run
=====================================

Use these instructions when running the package from Windows Explorer.

First-time setup
----------------

Double-click:

setup_environment.bat

This will:

- find an existing Conda or Anaconda installation
- install Miniconda only if Conda is not found
- create or update the dtalite_pipeline environment from setup/environment.yml
- run setup/check_setup.py using configs/project_assignment.json

The window pauses at the end so you can read success or error messages.

Run the pipeline
----------------

Double-click:

run_pipeline.bat

If no config is provided, a file picker opens in the configs folder. Select the JSON config you want to run. If you cancel, the script exits without running the pipeline.

To run a specific config from Command Prompt or PowerShell:

run_pipeline.bat configs\project_assignment.json

Logs
----

Run logs are written to:

logs\run_pipeline_log.txt

Setup logs are written to:

logs\setup_environment_log.txt

Important notes
---------------

- Keep setup_environment.bat and run_pipeline.bat in the project root folder.
- Keep the setup folder in the project root folder.
- Scenario folders should remain under the configured scenario_base_dir.
- The current workflow uses the installed Python DTALite package. It does not require DTALite_0324b.exe inside each scenario folder unless a future config explicitly enables an external executable workflow.
- If Windows shows a security warning, choose "More info" and then "Run anyway" only if you trust the package source.

Typical workflow
----------------

First time only:

1. Double-click setup_environment.bat.
2. Double-click run_pipeline.bat.

Future runs:

1. Double-click run_pipeline.bat.
