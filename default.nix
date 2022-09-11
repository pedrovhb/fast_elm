{ pkgs ? import <nixpkgs> {} }:
with pkgs;
  poetry2nix.mkPoetryApplication {
      projectDir = ./.;
      python = pkgs.python310;
      # buildInputs = [ pkgs.python310Packages.mypy ];
      # overrides = pkgs.poetry2nix.overrides.withDefaults (self: super: {
      # py3exiv2 = super.py3exiv2.overridePythonAttrs (old: {
      #   buildInputs = (old.buildInputs or [ ])
      #     ++ [ pkgs.exiv2 pkgs.python310Packages.boost ];
      # });
  }
