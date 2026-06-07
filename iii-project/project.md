# CareCircle AI — Platform & Integration Documentation

**CareCircle AI** is an AI-powered blood demand forecasting and care coordination network. It transitions blood support from reactive emergency response into a predictive planning system. Built on a retro-futuristic cyberpunk aesthetic framework, the platform provides continuous care coordination for chronic patients (e.g., Thalassemia, Sickle Cell) before shortages happen.

This document outlines the project goals, architecture, interactive features, and design guidelines that define the digital experience.

---

## 🌌 Narrative & Core Philosophy
Rather than relying on uncoordinated manual searches and panic messaging during crises, CareCircle AI models recurrent blood demands:
* **The Real Problem**: Patients needing blood (like Thalassemia patients on a 21-day cycle) suffer from coordination delay because preparation only starts in the final days.
* **Proactive Network**: The platform predicts the next likely transfusion date, alerts primary donor groups in advance, prepares standby backup networks, and dispatches field coordinators.
* **Aesthetic Context**: Wrapped in a visual, high-contrast retro-cyberpunk command center grid that honors tactile, responsive terminal control layouts (e.g. tape deck controls mapped to dispatch timelines, vector-drawn city grid maps, and glow-pulsing diagnostic HUD telemetry).

---

## 🛠️ Technical Stack
The application runs on client-side vanilla web standards optimized for rapid load, responsiveness, and premium interactivity:
1. **HTML5**: Uses clean, semantic structure to maintain SEO compatibility and accessible heading hierarchies.
2. **Vanilla CSS3**: Employs an HSL tailored color token design system with fluid flex and grid responsive layouts, custom-animated keyframes, and scroll parallax properties.
3. **Vanilla JavaScript (ES6)**: Powers all real-time coordinate math, scroll binding, map sector hotspots, interactive timelines, and AWS Bedrock assistant requests.

---

## 🎨 Design System & Visual Tokens

The website enforces a flat-pane visual hierarchy, avoiding standard drop shadows to define depth through contrasting borders and surface offsets.

### 1. Color Palette
* **Primary Background (`--color-color-1` / `#202020`)**: A dark carbon slate base canvas.
* **Surface/Cards (`--color-color-2` / `#212e50`)**: Deep navy blue, reflecting diagnostic monitoring grids.
* **Secondary Text (`--color-color-3` / `#e0e9ff`)**: Crisp lavender-blue for comfortable readable contrast.
* **Accent / Action (`--color-color-4` / `#f9de71`)**: High-visibility cyber-yellow reserved for CTAs and status signals.
* **Primary Text (`--color-color-5` / `#ffffff`)**: Pure white headings.
* **Risk States**: Warning values mapped to `#ffcc00` (yellow) and Critical alerts mapped to `#ff5e62` (bright coral red).

### 2. Typography
* **Primary Headings (`--font-type-2-family` / `Jua`)**: Playful, high-impact rounded sans-serif.
* **Body & Telemetry (`--font-type-1-family` / `Ubuntu`)**: Humanist sans-serif for clean, high-density dashboard readability.

---

## ⚡ Core Interactive Features

### ☀️ Sticky Day-to-Night Parallax Scroll
The hero section slowly transitions from bright morning sky blue to dark neon cyberpunk night colors as the user scrolls, controlled dynamically via linear color interpolation (LERP) inside `app.js`. Bobbing vector boats, Danfo buses, and floating drones animate independently.

### 📊 Proactive Patient Diagnostics HUD
Simulates a live patient diagnostic panel in the story section:
* **Patient Case**: Anjali (Thalassemia)
* **Required Blood Group**: O- (High rarity alert)
* **Expected Need Window**: 3 Days (June 7)
* **Active Verified Donors**: 4 (Backup assignment)
* **Risk level status**: Flashing glow alert (CRITICAL).

### 🧭 Command Center & Interactive Hyderabad Map
A telemetry interface demonstrating real-time sector-level tracking:
* **Shortage Forecast Widget**: Progress bars showing reserve status for O- (Critical), AB- (Warning), and B+ (Stable).
* **Interactive SVG City Map**: Multi-sector layout mapping Hyderabad North, Secunderabad, Cyberabad, and Hyderabad South.
* **Pulsing Hotspots**: Hover-active SVG hotspots. Clicking a hotspot populates the **Real Patient Journey** popover card showing detailed timeline records (e.g. Patient Kabir's sickle cell transfusion schedules vs Anjali's thalassemia preparation cycles).

### ⚙️ The Four Core Circles Grid
Replaces generic content columns with the four pillars of the predictive pipeline:
1. **Circle 01 — Predict**: AI models patient cycles to schedule requests 10 days out.
2. **Circle 02 — Prepare**: Sets primary lists and pre-warms backup networks.
3. **Circle 03 — Coordinate**: Tracks response confirmations and directs volunteer couriers.
4. **Circle 04 — Prevent**: Monitors timelines and triggers automated standby shifts.

### 🧠 Live AI Donor Circle Matcher
Interactive simulation panel in the scrolling zoom section:
* **Input Parameters**: Live form with dropdown selectors for blood group, location, and required dates.
* **SVG Concentric Circle Tracker**: Animated rings highlighting the outward search progression (Patient Request -> Primary -> Backup -> Emergency).
* **Amazon Bedrock Connection**: Sends assistant and extraction requests through the AWS AI Lambda without exposing provider credentials in the browser.
* **Robust Offline Fallback**: Safely catches network or API failures and runs a structured local simulation matching the requested blood group.

### 📻 Emergency Dispatch Timeline Player
A tape-recorder style progress module representing active dispatch logs:
* **7 Timeline Milestones**: Cycles from *Request Created* through *Backup Circle Activated* to *Blood Ready*.
* **Interactive Scrubber**: The user can click or drag across the progress bar to manually inspect different dispatch phases.
* **Rotating Spindles**: Cassette spindles rotate via CSS keyframes whenever the dispatch progress playback loop is running.

---

## 📂 Codebase File Structure
* [index.html](file:///c:/Users/soura/OneDrive/Documents/iii/index.html): Page markup structure, SVG vector maps, forms, and timeline containers.
* [style.css](file:///c:/Users/soura/OneDrive/Documents/iii/style.css): Global variables, layout grid rules, pulsing animations, and glowing states.
* [app.js](file:///c:/Users/soura/OneDrive/Documents/iii/app.js): Scroll interpolation controls, interactive dispatch loop, map sector state binds, and LLM matching handler.

---

## 🚀 Running the Project
1. Open the project root folder.
2. Spin up a local server:
   ```powershell
   python -m http.server 8000
   ```
3. Navigate to `http://localhost:8000` in any web browser.
