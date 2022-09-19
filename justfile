

run:
  poetry run python fast_elm/main.py

fmt:
  poetry run black .
  poetry run isort . --profile=black

check:
  poetry run mypy .

# todo bump, flake8, ...
