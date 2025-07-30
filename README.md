# PatchWise

<!-- [![License](https://img.shields.io/badge/license-XXX-blue.svg)](LICENSE) -->
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
<!-- [![Build Status](https://img.shields.io/badge/build-passing-brightgreen.svg)](#) -->

> **PatchWise** automates patch review and static analysis for the Linux kernel, streamlining upstream contributions and ensuring code quality.

---

## Table of Contents

- [Features](#features)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
- [Usage](#usage)
- [Command-Line Options](#command-line-options)
- [Development](#development)
- [Contact](#getting-in-contact)
- [License](#license)

---

## Features

- **Automated Patch Review**: Runs static analysis and style checks on kernel patches.
- **Integration with Mailing Lists**: Processes patches sent via email and responds automatically.
- **Flexible Review Selection**: Choose which review checks to run.
- **Rich Logging**: Colorized and file-based logging for easy debugging.
- **LLM Integration**: Uses Artificial Intelligence for commit message analysis and suggestions.
- **AI Code Review**: Leverages artificial intelligence to provide insights on code quality and potential issues. Integrated with Language Server Protocol (LSP) for context-aware code review. Support for multiple LLMs and providers, including OpenAI.

---

## Getting Started

### Prerequisites

- Python 3.10 or newer
- Access to a Linux kernel git repository

### Installation

1. **Clone the repository:**

   ```bash
   git clone https://github.com/qualcomm/PatchWise.git
   cd PatchWise
   ```

1. **Create and activate a virtual environment:**

   ```bash
   python3.10 -m venv .venv
   source .venv/bin/activate
   ```

1. **Install dependencies:**

   ```bash
   pip install .
   ```

1. **Set up your API key:**

   Obtain your API key from your provider and set it as an environment variable:

   ```bash
   export OPENAI_API_KEY=<your-api-key>
   ```

   Add this line to your shell profile (e.g., `~/.bashrc` or `~/.zshrc`) for persistence.

1. **Run help message:**

   ```bash
   patchwise --help
   ```

## Usage

1. **Run PatchWise:**

   Run PatchWise in the root of your kernel workspace:

   ```bash
   patchwise
   ```

   By default, PatchWise will review the `HEAD` commit. Use the `--commits` flag to review a specific commit:

   ```bash
   patchwise --commits <commit-sha>
   ```

   To run only short reviews, use:

   ```bash
   patchwise --short-reviews
   ```

   To run specific reviews, use the `--reviews` flag:

   ```bash
   patchwise --reviews checkpatch dt_checker
   ```

   To see available reviews and other options, run:

   ```bash
   patchwise --help
   ```

### Example Workflow

```bash
# Replace with a path on your system where you would like to download patchwise
cd /local/mnt/workspace/dgantman/kernel-tools

### Clone the repository
git clone https://github.com/qualcomm/PatchWise.git
cd /local/mnt/workspace/dgantman/kernel-tools/PatchWise

### Create and activate a virtual environment
python3.10 -m venv .venv
# Required every time you start a new shell session
source /local/mnt/workspace/dgantman/kernel-tools/PatchWise/.venv/bin/activate 
# Required every time you update the codebase
pip install /local/mnt/workspace/dgantman/kernel-tools/PatchWise
# Required every time you start a new shell session
# unless you've added it to your shell profile (e.g., ~/.bashrc or ~/.zshrc)
# You can find your API key from your provider
export OPENAI_API_KEY=<your-api-key>

### Run PatchWise in your kernel workspace that has the patch you want to review already applied
cd /local/mnt/workspace/dgantman/linux-next
patchwise --all-reviews
```

---

## Command-Line Options

- `-h`, `--help`: Show help message and exit

### Patch Review Options

- `--commits`: Space separated list of commit SHAs/refs, or a single commit range in start..end format. (default: [`HEAD`])
- `--repo-path`: Path to the kernel workspace root. Uses your current directory if not specified. (default: `$PWD`)
- `--reviews`: Space-separated list of reviews to run. (default: all available reviews)
- `--short-reviews`: Run only short reviews. Overrides `--reviews`.
- `--install`: Install missing dependencies for the specified reviews. This will not run any reviews, only install dependencies.

### Ai Review Options

- `--model`: Specify the AI model to use for code review. (default: `openai/Pro`).
- `--provider`: The base URL for the AI model API. (default: `https://api.openai.com/v1`)
- `--api-key`: The API key for the AI model API. If not provided, it will be read from the `OPENAI_API_KEY` environment variable.

### Logging Options

- `--log-level`: Set the logging level. (default: `INFO`)
- `--log-file`: Path to the log file (default: `<package_path>/sandbox/patchwise.log`)

## Development

If you'd like to develop new features or fix existing issues:

- Fork the repository and create a new branch for your changes.
- Make your changes with clear, descriptive commit messages.
- Ensure your code follows the project's coding standards and passes all tests.
- Submit a pull request (PR) with a detailed description of your changes to pull your changes into the staging branch in the main repository.

Please make sure to follow our contribution guidelines before submitting a pull request. [CONTRIBUTING.md](CONTRIBUTING.md)

## Getting in Contact

- [Report an Issue on GitHub](../../issues/new/choose)
- [Open a Discussion on GitHub](../../discussions/new/choose)
- [E-mail us](mailto:dgantman@quicinc.com) for general questions

## License

PatchWise is licensed under the BSD-3-clause License. See [LICENSE.txt](LICENSE.txt) for the full license text.
