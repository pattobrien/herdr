# pattobrien/herdr

This repository is a fork of [herdrdev/herdr](https://github.com/herdrdev/herdr). It builds its
own binaries with GitHub Actions and publishes them as GitHub Releases, so the fork can be installed
with mise instead of built locally.

## What this fork carries

- Input lag fix while kitty graphics panes stream: uploads are deflated and the client keeps a
  separate frame channel that gives keyboard input priority. No upstream PR.
- Input-latency benchmark harness in `bench/`. No upstream PR.
- Version parsing tolerates a pre-release suffix such as `0.9.3-fork.1` in `src/update.rs`. Required
  for every fork version; without it the server panics at startup. No upstream PR.
- `client.sidebar.toggle` API method and `herdr terminal sidebar toggle` CLI. No upstream PR.
- Pane OSC 22 pointer shapes are mirrored on the host cursor. No upstream PR.
- The API server reads the request line in chunks and waits with poll, cherry-picked from
  [mgpai22/herdr](https://github.com/mgpai22/herdr) commit f61be9c9. No upstream PR.
- The fork release workflow `.github/workflows/release-fork.yml`, this file, and `mise.toml`, which
  declares the Zig series the vendored libghostty-vt requires.

Remove an item from this list once upstream ships an equivalent and a sync brings it in. The
cell-centre SGR-pixels mouse fix was dropped on 2026-10-10 because upstream
[#5017](https://github.com/herdrdev/herdr/pull/5017) closed
[herdrdev/herdr#4750](https://github.com/herdrdev/herdr/issues/4750) another way.

## Releases

A fork tag is `v<upstream>-fork.N`, where `<upstream>` is the `version` in `Cargo.toml` that the
last sync brought in. For example, tag `v0.9.3-fork.1` publishes release `v0.9.3-fork.1` with the
assets `herdr-macos-aarch64` and `herdr-linux-x86_64`. N increases with every fork release and never
reuses a number that has a tag.

The workflow verifies that the tag equals the `Cargo.toml` version, so each release needs a commit
that sets `version` in `Cargo.toml` and `Cargo.lock` to `<upstream>-fork.N`.

## Cutting a release

1. On a branch from `master`, set `version = "<upstream>-fork.N"` in `Cargo.toml`, run
   `cargo update --workspace` so `Cargo.lock` follows, and commit as
   `release: v<upstream>-fork.N`.
2. Merge the branch into `master` through a PR.
3. Tag the merge commit and push the tag:

   ```sh
   git tag v<upstream>-fork.N <sha>
   git push origin v<upstream>-fork.N
   ```

The tag push starts `release-fork.yml`. It builds `aarch64-apple-darwin` and
`x86_64-unknown-linux-musl` with Rust 1.96.1 and Zig 0.16.0, the same toolchains as upstream's
`release.yml`, and publishes the release marked as latest. Upstream's `release.yml` also matches
the tag, but every job in it is skipped outside `herdrdev/herdr`.

To publish an existing fork tag again, run the workflow by hand with the `version` input:

```sh
gh workflow run release-fork.yml -R pattobrien/herdr -f version=<upstream>-fork.N
```

## Installing

In the mise config:

```toml
"github:pattobrien/herdr" = "latest"
```

mise picks the asset by OS and architecture, so no `asset_pattern` is needed.

## Syncing from upstream

Add the upstream remote once with `git remote add upstream https://github.com/herdrdev/herdr.git`.

1. Create a branch from `master`.
2. Merge upstream into the branch:

   ```sh
   git fetch upstream
   git merge --no-ff upstream/master
   ```

   Give the merge commit a conventional subject such as
   `chore: merge herdrdev/herdr master into fork master`; CI rejects anything else.

3. Open a PR into `master`.

Never rebase or force-push `master` or any pushed branch.

## Building locally

`mise.toml` pins Zig to the 0.16 series because `vendor/libghostty-vt` accepts exactly that minor
version. Run `mise trust` once in the checkout, then `cargo build` as usual.
