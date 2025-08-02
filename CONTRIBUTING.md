# Contributing to PatchWise

Hi there!
We’re thrilled that you’d like to contribute to this project.
Your help is essential for keeping this project great and for making it better.

## Branching Strategy

In general, contributors should develop on branches based off of `main` and pull requests should be made against `main`.

## Setting up development environment
```bash
pip install -e .[dev]
```

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

1. Make sure your changes adhere to our style rules.
    
    Format your changes with Ruff:
    ```bash
    ruff format .
    ```

    Check for linter errors with Ruff
    ```bash
    ruff check . 
    ```

    If any errors are found, Ruff may be able to automatically apply appropriate changes:
    ```bash
    ruff check --fix .
    ```


1. Commit your changes using the [DCO](https://developercertificate.org/). You can attest to the DCO by commiting with the **-s** or **--signoff** options or manually adding the "Signed-off-by":

    ```bash
    git commit -s -m "Really useful commit message"`
    ```

    **NOTE:** Try to keep commits as atomic as possible

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

- Before submitting a pull request, please format your Python code using Ruff - https://docs.astral.sh/ruff/. 
- Write tests.
- Keep your change as focused as possible.
  If you want to make multiple independent changes, please consider submitting them as separate pull requests.
- Write a [good commit message](https://tbaggery.com/2008/04/19/a-note-about-git-commit-messages.html).
- It's a good idea to arrange a discussion with other developers to ensure there is consensus on large features, architecture changes, and other core code changes. PR reviews will go much faster when there are no surprises.


## Python style
This project uses the pre-commit tool to maintain code quality and consistency. Before submitting a pull request or making any commits, it is important to run the pre-commit tool to ensure that your changes meet the project's guidelines.

Furthermore, we have integrated a pre-commit GitHub Action into our workflow. This means that with every pull request opened, the pre-commit checks will be automatically enforced, streamlining the code review process and ensuring that all contributions adhere to our quality standards.

To run the pre-commit tool, follow these steps:
- Use absolute imports instead of relative. Relative imports from siblings are acceptable. 
- Include type hints for function parameters and return types. Exceptions to this rule are `__init__` functions not requiring return types, as well as dummy parameters.
- Unless otherwise specified, follow PEP 8.

