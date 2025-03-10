# scoop-alts

This repository provides alternative [Scoop](https://scoop.sh/) buckets for various applications, focusing on enhanced functionality, customized configurations, and quality-of-life (QoL) improvements.

Notably, it includes a bucket with **ungoogled-chromium** that has **Widevine support**, allowing you to enjoy DRM-protected content on a privacy-focused browser.
Additionally, you'll find other buckets with tailored configurations and tweaks to improve your overall experience.

## Featured Buckets and Improvements

* **ungoogled-chromium with Widevine:**
    * Addresses the common limitation of standard ungoogled-chromium distributions: the absence of Widevine support.
    * Allows access to DRM-protected content on platforms like Netflix, Amazon Prime Video, and Spotify Web Player.
    * Maintains privacy by using ungoogled-chromium, while incorporating Widevine in a way that minimizes Google integration.
* **Other Customized Buckets:**
    * This repository will contain other buckets with customized configurations.
    * QoL improvements and tweaks to enhance application functionality.

**Important Note:** Enabling Widevine on ungoogled-chromium involves incorporating proprietary components. While this is done in a way that minimizes Google integration, it's crucial to understand that it introduces a trade-off between absolute privacy and functionality.

## Adding the [Scoop](https://scoop.sh/) Bucket

To add the `scoop-alts` bucket to your [Scoop](https://scoop.sh/) installation, follow these steps:

1.  **Open Terminal:** Launch your preferred terminal as an administrator.
2.  **Add the bucket:** Execute the following command:

    ```powershell
    scoop bucket add scoop-alts https://github.com/danalec/scoop-alts
    ```

## Installing Ungoogled-Chromium with Widevine

After adding the bucket, you can install ungoogled-chromium with Widevine support:

1.  **Update [Scoop](https://scoop.sh/) (Recommended):** Ensure your installation is up-to-date:

    ```powershell
    scoop update
    ```

2.  **Install ungoogled-chromium:** Install the browser using the following command:

    ```powershell
    scoop install scoop-alts/ungoogled-chromium
    ```

**You might need to also run `scoop config force_update $true` in session to not have scoop disregard updates from this bucket.**

## Usage

Once installed, you can launch ungoogled-chromium from your Start Menu `Chromium`.
To verify Widevine is working, navigate to a website that uses it, such as Netflix or Crunchyroll, and attempt to play a video.

## Contributing

Contributions to this repository are welcome. If you have improvements or new bucket suggestions, please submit a pull request.

## License

This is free and unencumbered software released into the public domain.

Anyone is free to copy, modify, publish, use, compile, sell, or distribute this software, either in source code form or as a compiled binary, for any purpose, commercial or non-commercial, and by any means.

In jurisdictions that recognize copyright laws, the author or authors of this software dedicate any and all copyright interest in the software to the public domain. We make this dedication for the benefit of the public at large and to the detriment of our heirs and successors. We intend this dedication to be an overt act of relinquishment in perpetuity of all present and future rights to this software under copyright law.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

For more information, please refer to <https://unlicense.org>

<details>
<summary>Thanks to the original authors of the manifests from the default Scoop buckets. </summary>

* https://raw.githubusercontent.com/ScoopInstaller/Extras/master/bucket/ungoogled-chromium.json
</details>