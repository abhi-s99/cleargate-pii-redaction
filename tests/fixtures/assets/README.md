# Test assets

| File | Source | Licence | Use |
|---|---|---|---|
| `face_public_domain.png` | scikit-image test image `astronaut.png` (tag v0.24.0, `skimage/data/astronaut.png`, sha256 `88431cd9653ccd539741b555fb0a46b61558b301d4110412b5bc28b5e3ea6cb5`): NASA photograph of astronaut Eileen Collins, downscaled to 256x256 (sha256 `f62eadbadded279aee27e47437592a38070a01446e08130baa93c9fdc6ed1517`) | Public domain (work of the US federal government, NASA); scikit-image lists it as public domain | A real face so the Haar face detector (TR-EX-06) has something to find in synthetic fixtures. Not related to the case study. |

The image is the standard computer-vision test photo. It is used only as a face-like
region inside generated fixtures; no other data about the person is used anywhere.
