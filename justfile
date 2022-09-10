

fmt:
  poetry run black .
  poetry run isort . --profile=black

check:
  poetry run mypy .

# todo bump, flake8, ...
