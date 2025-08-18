# Contributing to PatchWise

Hi there!
We’re thrilled that you’d like to contribute to this project.
Your help is essential for keeping this project great and for making it better.

## Branching Strategy

In general, contributors should develop on branches based off of `main` and pull requests should be made against `main`.

## Setting up development environment

1. Install PatchWise in editable mode with developer dependancies:

    ```bash
    pip install -e ".[dev]"
    ```

1. After installing the development dependencies, set up pre-commit hooks to run code quality checks:

    ```bash
    pre-commit install
    ```

    For more information about our pre-commit checks, see [style guidelines](#running-pre-commit).

## Submitting a pull request

1. Please read our [code of conduct](CODE-OF-CONDUCT.md) and [license](LICENSE.txt).

1. [Fork](../../fork) and clone the repository.

    ```bash
    git clone https://github.com/qualcomm/PatchWise.git
    ```

1. Create a new branch based on `main`:

    ```bash
    git checkout -b <my-branch-name> main
    ```

1. Create an upstream `remote` to make it easier to keep your branches up-to-date:

    ```bash
    git remote add upstream https://github.com/qualcomm/PatchWise.git
    ```

1. Make your changes, add tests, and make sure the tests still pass.

1. Make sure your changes adhere to our [code style guidelines](#python-style).

1. Commit your changes using the [DCO](https://developercertificate.org/). You can attest to the DCO by commiting with the **-s** or **--signoff** options or manually adding the "Signed-off-by":

    ```bash
    git commit -s -m "Really useful commit message"`
    ```

     > **NOTE:** Keep each commit focused on a single logical change. Avoid large commits which encompass multiple changes.

1. After committing your changes on the topic branch, sync it with the upstream branch:

    ```bash
    git pull --rebase upstream main
    ```

1. Push to your fork.

    ```bash
    git push -u origin <my-branch-name>
    ```

    The `-u` is shorthand for `--set-upstream`. This will set up the tracking reference so subsequent runs of `git push` or `git pull` can omit the remote and branch.

1. [Submit a pull request](../../pulls) from your branch to `main`.

1. Pat yourself on the back and wait for your pull request to be reviewed.

Here are a few things you can do that will increase the likelihood of your pull request to be accepted:

- Before submitting a pull request, please format your Python code using Ruff - <https://docs.astral.sh/ruff/>.
- Write tests.
- Keep your change as focused as possible.
  If you want to make multiple independent changes, please consider submitting them as separate pull requests.
- Write a [good commit message](https://tbaggery.com/2008/04/19/a-note-about-git-commit-messages.html).
- It's a good idea to arrange a discussion with other developers to ensure there is consensus on large features, architecture changes, and other core code changes. PR reviews will go much faster when there are no surprises.

## Python style

This project uses the pre-commit tool to maintain code quality and consistency. Before submitting a pull request or making any commits, it is important to run the pre-commit tool to ensure that your changes meet the project's guidelines.

Furthermore, we have integrated a pre-commit GitHub Action into our workflow. This means that with every pull request opened, the pre-commit checks will be automatically enforced, streamlining the code review process and ensuring that all contributions adhere to our quality standards.

### Code style guidelines

This project enforces the following rules for Python:

- **Follow PEP 8**: We enforce [pycodestyle errors (E)](https://pycodestyle.pycqa.org/en/latest/intro.html#error-codes) and [warnings (W)](https://pycodestyle.pycqa.org/en/latest/intro.html#warning-codes)
- **Line length**: Maximum of 88 characters
- **Use absolute imports**: Import from the full module path (e.g., `from patchwise.module import function` instead of `from ..module import function`)
  - *Exception*: Relative imports from siblings are acceptable (e.g., `from .sibling import function`)
- **Import sorting**: Imports are automatically sorted using isort rules with `patchwise` as a known first-party package
- **Include type hints** for function parameters and return types
  - *Exception*: `__init__` functions don't require return type annotations, dummy parameters may omit type hints

#### Ruff Configuration Details

Our Ruff configuration enforces:

- **E codes**: [Pycodestyle errors](https://docs.astral.sh/ruff/rules/#pycodestyle-e) (syntax errors, indentation issues, etc.)
- **W codes**: [Pycodestyle warnings](https://docs.astral.sh/ruff/rules/#pycodestyle-w) (whitespace issues, deprecated features, etc.)  
- **TID252**: [Require absolute imports](https://docs.astral.sh/ruff/rules/banned-relative-import/)
- **I codes**: [Import sorting](https://docs.astral.sh/ruff/rules/#isort-i) (import organization and formatting)

For a complete list of rules and their descriptions, see the [Ruff rules documentation](https://docs.astral.sh/ruff/rules/).

### Running pre-commit

The pre-commit hooks will automatically run when you make commits and will prevent you from making any commits that fail our linting + formatting checks.

To manually run pre-commit on all files:

```bash
pre-commit run --all-files
```

To commit changes which fail the pre-commit checks, you can use the **--no-verify** flag to force the commit:

```bash
git commit -s -m "Unverified commit" --no-verify
```

### Manual formatting and linting with Ruff

If you need to run the tools manually without pre-commit:

Format your changes with Ruff:

```bash
ruff format .
```

Check for linter errors with Ruff:

```bash
ruff check . 
```

If any errors are found, Ruff may be able to automatically apply appropriate changes:

```bash
ruff check --fix .
```

## Markdown style

This project also includes a linter for markdown files within the GitHub Actions code quality checks. This linter enforces the default rules defined by [markdown-cli](https://github.com/DavidAnson/markdownlint-cli2.git), which is also available as a [VSCode extension](https://marketplace.visualstudio.com/items?itemName=DavidAnson.vscode-markdownlint).

### Manual formatting with markdown-cli

To run the markdown linter manually, first install the required dependency using Node.js >= 18:

```bash
npm install 
```

To check for errors:

```bash
npm run lint:md
```

To apply automatic fixes:

```bash
npm run lint:md:fix
```
