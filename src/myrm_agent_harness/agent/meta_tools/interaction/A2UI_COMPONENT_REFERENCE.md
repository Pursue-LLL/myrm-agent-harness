# A2UI Component Reference

> Allowed types (must match harness `UIComponentType`): text, button, button_group, text_field, textarea, select, date_picker, time_picker, slider, checkbox, radio, switch, container, card, divider, grid, tabs, table, list, image, chart, progress, badge

Load this file via `file_read_tool` before building complex UI (table, chart, tabs, multi-step forms).

## JSON shape

```json
{
  "title": "Human-readable title",
  "components": [{"id": "...", "type": "...", "props": {}, "children": [], "bindings": {}, "events": {}}],
  "root_ids": ["root_component_id"],
  "data": {},
  "actions": [{"id": "...", "type": "submit|cancel|navigate|custom", "label": "...", "payload": {}}]
}
```

Components use a **flat adjacency list**: `children` holds child component IDs.

## Basic components

- **text**: `props.text`, `props.variant` (body|heading|caption)
- **button**: `props.label`, `props.variant` (primary|secondary|outline|ghost|danger), `props.loading`, `props.fullWidth`, `props.size` (sm|md|lg)
- **button_group**: `children` = button IDs (single/multi select)

## Form components

- **text_field**: `label`, `placeholder`, `type` (text|email|password|number)
- **textarea**: `label`, `placeholder`, `rows`
- **select**: `label`, `options` (string[] or `{value,label}[]`)
- **date_picker**: `label`, `minDate`, `maxDate`
- **time_picker**: `label`, `minTime`, `maxTime`, `step`
- **slider**: `label`, `min`, `max`, `step`, `showValue`
- **checkbox** / **radio** / **switch**: `label`; radio also `options`, `layout` (horizontal|vertical)

Validation in `props`: `required`, `minLength`, `maxLength`, `pattern`, `min`, `max`, `validation: [{type, value, message}]`

## Layout components

- **container** / **card**: `children`; card may have `props.title`
- **grid**: `columns`, `gap`, `mobileColumns`, `tabletColumns`
- **tabs**: `props.tabs: [{label}]`, `children` order matches tabs; optional `defaultIndex`
- **divider**

## Data display

- **table**: `props.columns: [{key, title}]`, bind rows via `bindings.data`; optional `props.selectable` + `bindings.selected` (string[] row ids) + `props.rowIdKey` (default `id`)
- **chart**: `type` (bar|line|pie|donut), `title`, `showLegend`, `showValues`
- **image**: `src`, `alt`, `caption`, `objectFit` (cover|contain)
- **progress**: `value`, `max`, `showLabel`
- **badge**: `text`, `variant` (default|success|warning|error)
- **list**: bind rows via `bindings.data` (`{id?, title, subtitle?, description?}[]`); optional `props.bordered`, `props.compact`, `props.emptyText`, `props.className`; or use `children` for adjacency-list items

## Bindings and visibility

- `bindings`: map prop names to data paths, e.g. `"value": "$.form.name"`
- Conditional: `visible: "path.to.value"` or `visible: "path == 'value'"` in bindings/props

## Minimal example (no need to read this file)

```json
{
  "title": "Quick confirm",
  "components": [
    {"id": "q", "type": "text", "props": {"text": "Proceed?", "variant": "body"}},
    {"id": "ok", "type": "button", "props": {"label": "Yes"}, "events": {"onClick": "yes"}}
  ],
  "root_ids": ["q", "ok"],
  "actions": [{"id": "yes", "type": "submit", "label": "Confirm"}]
}
```
