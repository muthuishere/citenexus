## ADDED Requirements

### Requirement: Conditional vision pre-filter decision

The system SHALL provide a pure `decide(image, *, page_area, ocr_text_dense, config)`
that routes a single `ImageRef` to exactly one `VisionDecision` of `text`, `ocr`,
`vision`, or `skip`, without performing any I/O, network call, or model
invocation. The decision SHALL follow §9: a text-native page (signaled by
`page_area` being `None`) routes to `text`; an image covering less than
`config.min_area_ratio` of its page, or whose aspect ratio falls outside the
configured `min_aspect_ratio`/`max_aspect_ratio` bounds, routes to `skip`; an
OCR-dense raster routes to `ocr` when `config.skip_if_ocr_dense` is true and
otherwise to `vision`; and any remaining meaningful figure routes to `vision`.
The `VisionPrefilterConfig` SHALL be frozen, reject unknown fields, and default
to `min_area_ratio=0.05`, `skip_if_ocr_dense=True`, and non-null aspect-ratio
bounds.

#### Scenario: Text-native page routes to text

- **WHEN** `decide` is called for an image with `page_area=None`
- **THEN** it returns `VisionDecision.text` and no model is invoked

#### Scenario: OCR-dense raster routes to ocr

- **WHEN** an image clearing `min_area_ratio` and the aspect bounds is decided
  with `ocr_text_dense=True` under default config
- **THEN** it returns `VisionDecision.ocr`

#### Scenario: Meaningful figure routes to vision

- **WHEN** an image clearing `min_area_ratio` and the aspect bounds is decided
  with `ocr_text_dense=False`
- **THEN** it returns `VisionDecision.vision`

#### Scenario: Tiny decoration below the area ratio is skipped

- **WHEN** an image covering less than `min_area_ratio` of its page is decided
- **THEN** it returns `VisionDecision.skip`

#### Scenario: Banner aspect ratio is skipped

- **WHEN** an image whose area clears `min_area_ratio` but whose aspect ratio
  exceeds `max_aspect_ratio` is decided
- **THEN** it returns `VisionDecision.skip`

#### Scenario: skip_if_ocr_dense toggle is honored

- **WHEN** an OCR-dense meaningful image is decided with
  `VisionPrefilterConfig(skip_if_ocr_dense=False)`
- **THEN** it returns `VisionDecision.vision` instead of `VisionDecision.ocr`

### Requirement: Vision description orchestration

The system SHALL provide `describe_image(image, plugin)` that calls the injected
`VisionPlugin` for an `ImageRef` and shapes its result into a frozen,
extra-forbidding `VisionRecord` carrying the image's id, a `short_caption`, a
`detailed_description`, `objects`, `relationships`, and `ocr_text`. The system
SHALL NOT bundle a vision model; real inference is delegated to the injected
plugin. The system SHALL ship a deterministic `FakeVision` plugin that produces a
populated record with no network access, for hermetic tests.

#### Scenario: Describe shapes plugin output into an EU-ready record

- **WHEN** `describe_image` is called with an `ImageRef` and `FakeVision`
- **THEN** it returns a `VisionRecord` for that image id with a non-empty
  `short_caption`, `detailed_description`, `objects`, `relationships`, and
  `ocr_text`, and no network is accessed

#### Scenario: FakeVision is a conforming versioned plugin

- **WHEN** a `FakeVision` instance is inspected
- **THEN** it is an instance of `VisionPlugin` and carries a non-empty
  `plugin_version`
