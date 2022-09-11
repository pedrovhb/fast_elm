{ pkgs ? import <nixpkgs> {} }:
let
  myAppEnv = pkgs.poetry2nix.mkPoetryEnv {
    projectDir = ./.;
    python = pkgs.python310;
    editablePackageSources = {
      fast_elm = ./fast_elm;
    };
    
  };
# in myAppEnv.env
in myAppEnv.env.overrideAttrs (oldAttrs: {
  buildInputs = [ pkgs.python310Packages.mypy ];
})
