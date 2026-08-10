<section class="sm-hero">
  <div class="sm-hero__copy">
    <div class="sm-eyebrow">Godot 4.6.1 · Gate A</div>
    <h1>Make collisions sound <span>alive.</span></h1>
    <p class="sm-hero__lede">
      Physics-driven, controllable Foley for games—local-first, deterministic,
      and deliberately small enough to run without a model server or high-end GPU.
    </p>
    <div class="sm-actions">
      <a class="sm-button sm-button--primary" href="getting-started/">Build your first material →</a>
      <a class="sm-button sm-button--secondary" href="https://github.com/andyandymike/sonic-matter">View source on GitHub</a>
    </div>
  </div>
  <div class="sm-signal" aria-hidden="true">
    <div class="sm-signal__bars">
      <span style="--h: 24%; --d: -1.8s"></span>
      <span style="--h: 48%; --d: -0.4s"></span>
      <span style="--h: 78%; --d: -2.2s"></span>
      <span style="--h: 42%; --d: -1.1s"></span>
      <span style="--h: 96%; --d: -2.6s"></span>
      <span style="--h: 62%; --d: -0.7s"></span>
      <span style="--h: 36%; --d: -1.5s"></span>
      <span style="--h: 72%; --d: -2.9s"></span>
      <span style="--h: 52%; --d: -0.2s"></span>
      <span style="--h: 84%; --d: -2s"></span>
      <span style="--h: 28%; --d: -1.3s"></span>
    </div>
  </div>
</section>

<div class="sm-metrics">
  <div class="sm-metric">
    <strong>0 cloud calls</strong>
    <span>Offline-capable runtime</span>
  </div>
  <div class="sm-metric">
    <strong>≤ 8 voices</strong>
    <span>Hard Gate A ceiling</span>
  </div>
  <div class="sm-metric">
    <strong>Same seed</strong>
    <span>Reproducible selection</span>
  </div>
</div>

<section class="sm-section">
  <div class="sm-section__head">
    <div>
      <span class="sm-kicker">Why SonicMatter</span>
      <h2>Variation without a black box.</h2>
    </div>
    <p>
      Gate A starts from recorded impact variants and adds the event logic an
      independent game actually needs: intensity, repeat control, bounded
      variation, deterministic seeds, and a shared 3D voice budget.
    </p>
  </div>
  <div class="sm-card-grid">
    <article class="sm-card">
      <div class="sm-card__icon">01</div>
      <h3>Gameplay-aware</h3>
      <p>Collisions arrive as normalized events with intensity, position, priority, evidence, and stable identity.</p>
    </article>
    <article class="sm-card">
      <div class="sm-card__icon">02</div>
      <h3>Deterministic variation</h3>
      <p>Weighted selection avoids adjacent repeats and keeps pitch and gain changes inside authored bounds.</p>
    </article>
    <article class="sm-card">
      <div class="sm-card__icon">03</div>
      <h3>Engine-native playback</h3>
      <p>A shared AudioStreamPlayer3D pool provides positional output, observable counters, and deterministic stealing.</p>
    </article>
  </div>
</section>

<section class="sm-section">
  <div class="sm-section__head">
    <div>
      <span class="sm-kicker">Signal path</span>
      <h2>From contact to sound in four bounded steps.</h2>
    </div>
    <p>
      Each stage remains inspectable. There is no hidden inference service and
      no opaque prompt-to-audio step in the current runtime.
    </p>
  </div>
  <div class="sm-flow">
    <div class="sm-flow__step">
      <strong>Observe</strong>
      <span>A rigid body or gameplay system emits a normalized impact.</span>
    </div>
    <div class="sm-flow__step">
      <strong>Resolve</strong>
      <span>An acoustic material supplies eligible authored variants.</span>
    </div>
    <div class="sm-flow__step">
      <strong>Select</strong>
      <span>Seeded weighting and repeat policy choose bounded parameters.</span>
    </div>
    <div class="sm-flow__step">
      <strong>Play</strong>
      <span>The shared 3D pool allocates or deterministically replaces a voice.</span>
    </div>
  </div>
</section>

<section class="sm-section">
  <div class="sm-section__head">
    <div>
      <span class="sm-kicker">Current release line</span>
      <h2>Start with collisions. Prove the foundation.</h2>
    </div>
    <p>
      The project intentionally ships the sample-first event foundation before
      native synthesis, learned fitting, retrieval, or broad material coverage.
    </p>
  </div>
  <div class="sm-boundary">
    <div class="sm-boundary__badge">EXPERIMENTAL</div>
    <p>
      Gate A is not production Foley and does not yet include resonators,
      footsteps, scrape, roll, ambience, or an exported-package guarantee.
      Read the <a href="gate-a-contract/">public contract</a> before integrating
      it into a shipping project.
    </p>
  </div>
  <div class="sm-actions">
    <a class="sm-button sm-button--primary" href="getting-started/">Open the getting-started guide →</a>
  </div>
</section>
