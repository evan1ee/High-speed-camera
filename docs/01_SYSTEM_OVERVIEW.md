# System & Hardware Specifications

This document details the physical test rig, imaging hardware, optical configuration, and mechanical operational constraints for the high-speed camera needle-free injector test system.

---

## 1. Physical Test Rig & Application Domain

### 1.1 Needle-Free Injection Principle
Needle-free injectors deliver liquid medicine subcutaneously or intramuscularly without a hypodermic needle. An actuator (mechanical spring, compressed gas, or pyrotechnic charge) drives a small piston down a transparent ampoule. This forces the drug formulation through a micro-orifice (typically $\sim 150\ \mu\text{m}$ to $200\ \mu\text{m}$ in diameter) at high pressure, creating a fine liquid jet with speeds exceeding $100\ \text{m/s}$ to $250\ \text{m/s}$.

### 1.2 Rig Geometry & Coordinate Space
- **Mounting**: The injector and camera are rigidly mounted on an optical bench.
- **Orientation**: By hardware assembly convention, the **injector nozzle is located on the RIGHT-hand side** of the camera field of view, spraying horizontally toward the **LEFT**.
- **Coordinate Conventions**:
  - Image coordinates: $(0, 0)$ is the top-left pixel.
  - Horizontal axis ($X$): Increasing from left to right ($0 \dots \text{Width} - 1$).
  - Vertical axis ($Y$): Increasing from top to bottom ($0 \dots \text{Height} - 1$).
  - Jet propagation direction: Directed along $-X$ (right to left).

```
+-------------------------------------------------------------+
| Image (0,0)                                                 |
|                                            [ Injector Body] |
|   <==== Water Jet <====                   +--[ Nozzle Tip ] |
|                                            |  (Right Side)  |
|                                                             |
+-------------------------------------------------------------+
```

---

## 2. Camera Specifications

The system utilizes an industrial high-speed camera: **Huaray / iRayple AH7040MU000**.

### 2.1 Sensor Details
- **Sensor Type**: CMOSIS CMV4000 monochrome CMOS area sensor.
- **Pixel Array**: $2048 \times 2048$ pixels ($4.2\ \text{Megapixels}$).
- **Pixel Size**: $5.5\ \mu\text{m} \times 5.5\ \mu\text{m}$.
- **Shutter Type**: Global shutter (vital for freezing high-speed motion without rolling shutter distortion).
- **Interface**: USB 3.0 (SuperSpeed) / USB3 Vision protocol.
- **Bit Depth**: 8-bit output (`Mono8`, 1 byte per pixel).

### 2.2 Critical Sensor Characteristics
1. **Monochrome Sensor Architecture**:
   - The camera model suffix `M` denotes a pure monochrome sensor without a Bayer Color Filter Array (CFA).
   - Analysis of raw captured pixel data confirms zero Bayer mosaic pattern (fixed-pattern row/column variance is $<0.6\%$, whereas a CFA read as Mono8 exhibits $10\%\dots30\%$ parity divergence).
   - **Operational Consequence**: Any visual feature (liquid jet, dye in gel, piston boundary, or calibration mark) must contrast in **radiometric luminance (grayscale brightness)**. Dyes differing only in chromatic hue but identical in luminance are invisible to this camera.
2. **Readout Rate vs. Exposure**:
   - The sensor frame rate is **row-readout bound**, governed by horizontal line transmission time, **not exposure time**.
   - Reducing exposure from $500\ \mu\text{s}$ to $100\ \mu\text{s}$ or $50\ \mu\text{s}$ does **NOT** increase the achievable frame rate.
   - Frame rate increases are achieved solely by reducing the vertical height (ROI cropping) of the readout window.
3. **Free-Running Acquisition**:
   - In standard burst modes, `AcquisitionFrameRateEnable` is kept `False`. The camera free-runs at the maximum hardware transfer rate achievable for the configured ROI over USB 3.0.

---

## 3. Aspect Ratio & ROI Presets

The system presets vertical and horizontal windows to maximize frame rate while maintaining sufficient field of view:

| Preset Name | Dimensions ($W \times H$) | Measured Rig FPS | Usable Barrel Rows | Use Cases & Notes |
| :--- | :--- | :--- | :--- | :--- |
| **`320x240`** | $320 \times 240$ px | **1,048 fps** | 79 rows | **Primary Default**: Standard spray angle, piston tracking, and spatial calibration. |
| **`320x120`** | $320 \times 120$ px | **1,798 fps** | 79 rows | High-speed piston travel and rapid injection transient resolution. |
| **`320x64`** | $320 \times 64$ px | **2,624 fps** | 48 rows | *Withdrawn from default UI*: Crops into the barrel walls. Piston appears gray with detaching collar. Requires careful mechanical realignment to fill the frame before use. |
| **`16:9`** | $576 \times 324$ px | $\sim 820$ fps | Full | Wide-angle observation and initial rig optical alignment. |
| **`4:3`** | $432 \times 324$ px | $\sim 820$ fps | Full | General test verification. |
| **`1:1`** | $332 \times 332$ px | $\sim 800$ fps | Full | Square observation. |

> [!IMPORTANT]
> **Cropping (ROI Change) Does Not Change Spatial Scale ($\text{mm}/\text{px}$)**:
> Spatial resolution is fixed by the optical focal length and working distance. A crop reduces the sensor area read out, but each remaining pixel covers the exact same physical distance in millimeters. Scale calibration remains valid across ROI changes, provided lens focus and physical positioning remain untouched.

---

## 4. Optical Setup & Illumination

### 4.1 Lens and Working Distance
- High-resolution C-mount telecentric or macro lens with manual focus and iris lock.
- Working distance: Typically $100\ \text{mm}\dots150\ \text{mm}$ from lens front to injector center.
- Typical spatial resolution: $0.030\ \text{mm/px}\dots0.065\ \text{mm/px}$ ($\sim 15\dots33\ \text{px/mm}$).

### 4.2 Illumination Modes
1. **Backlighting (Shadowgraphy / Silhouette)**:
   - High-intensity LED panel or collimated light source placed directly opposite the camera behind the test zone.
   - Piston appears as an opaque dark silhouette against a bright illuminated barrel interior.
   - Ideal for piston tracking and edge stability.
2. **Direct / Side Lighting**:
   - Used when illuminating the liquid spray cone. Droplets scatter incident light toward the lens, rendering the water jet bright white against a dark background.

---

## 5. Physical Injector Parameters

For hydrodynamic calculations (converting piston displacement and speed into liquid jet velocity and impact pressure), the following default parameters represent the qualified device geometry:

| Parameter | Symbol | Default Value | Unit | Definition |
| :--- | :--- | :--- | :--- | :--- |
| **Barrel Diameter** | $D_{\text{barrel}}$ | `6.12` | $\text{mm}$ | Internal diameter of the medicine ampoule cylinder. |
| **Orifice Diameter** | $D_{\text{orifice}}$ | `0.155` | $\text{mm}$ | Nozzle discharge orifice diameter. |
| **Fluid Density** | $\rho$ | `1000.0` | $\text{kg/m}^3$ | Density of test liquid (distilled water). |
| **Area Ratio** | $A_{\text{ratio}}$ | $1560.8$ | dimensionless | Ratio of barrel area to orifice area: $(D_{\text{barrel}} / D_{\text{orifice}})^2$. |

---

## 6. Testing Environments

1. **Free-Air Spray**:
   - Injection fired into ambient air.
   - The jet enters, forms a steady flow cone, and then clears the scene.
   - Background returns to its pre-injection dry state after dissipation.
2. **Ballistic Gel Block**:
   - Injection fired directly into a block of synthetic transparent ballistic gel (simulating human skin and tissue penetration).
   - **Crucial Characteristic**: The gel permanently deforms, fractures, and retains injected liquid. The scene **remains changed indefinitely**. Standard background subtraction cannot detect the end of the event because the background never recovers.
