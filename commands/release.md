# /release

Trigger the professional release pipeline.

## Logic

0. **Sync Check:** Ensure everything is saved, staged, and properly pushed.
    -   Check if there are any uncommitted changes: `git status`.
    -   If there are uncommitted changes, **STOP** and inform the user. Ask them if they want to commit now!
    -   If there are no uncommitted changes, continue.
1.  **Version Check:** 
    - Read `version` from `VERSION` file.
    - Fetch remote tags: `git fetch --tags`.
    - Verify `v<version>` does **not** already exist on remote or locally: `git tag -l v<version>`.
    - If tag exists, **STOP** and inform the user. Ask them if they want to bump now!
2.  **Git Tagging:**
    -   Verify the working directory is clean.
    -   Create a tag matching the version (e.g., `v0.2.0`).
    -   Push the specific tag to `origin`: `git push origin v<version>`.
3.  **CI Monitoring:** 
    -   Open the GitHub Actions Page: `open "https://github.com/markus-barta/flirc-bridge/actions"`.
    -   Explain that a Draft Release will be created upon completion.
    -   Run a watch command in shell: `gh run watch`. 
    -   Once finished, open the releases page: `open "https://github.com/markus-barta/flirc-bridge/releases"`.
 (Note: Still DocMost? Wait, I should check the origin URL)

## Requirements

-   Ensure `VERSION` file is bumped before calling.
-   Requires `origin` to be a GitHub repository.
-   GitHub CLI (`gh`) must be authenticated.

## Safety

-   Will not tag if there are uncommitted changes.
-   Will not push if the tag already exists on remote.
