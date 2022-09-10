{ pkgs ? import <nixpkgs> {} }:
let
  myAppEnv = pkgs.poetry2nix.mkPoetryEnv {
    projectDir = ./.;
    python = pkgs.python310;
    editablePackageSources = {
      fast_elm = ./fast_elm;
    };
  };
in myAppEnv.env
