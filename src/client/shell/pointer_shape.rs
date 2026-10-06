use super::*;
use crate::protocol::endpoint::EndpointPanePointerShape;

impl ClientShellState {
    pub(crate) fn set_endpoint_pane_pointer_shape(
        &mut self,
        endpoint_id: &ClientEndpointId,
        update: EndpointPanePointerShape,
    ) {
        let Some(endpoint) = self
            .endpoints
            .iter_mut()
            .find(|endpoint| &endpoint.endpoint_id == endpoint_id)
        else {
            return;
        };
        if update.shape.is_empty() {
            endpoint.pane_pointer_shapes.remove(&update.pane_id);
        } else {
            endpoint
                .pane_pointer_shapes
                .insert(update.pane_id, update.shape);
        }
    }

    /// The hovered pane's OSC 22 shape in terminal mode, or "" for the host default.
    fn hovered_pointer_shape(&self) -> &str {
        if self.mode != ClientShellMode::Terminal
            || self.overlay.is_some()
            || self.popup_pending
            || self.chrome_drag.is_some()
        {
            return "";
        }
        let Some(point) = self.last_mouse_position else {
            return "";
        };
        let hit = match self.hits.popup.as_ref() {
            Some(popup) => contains(popup.inner_rect, point).then_some(popup),
            None => self
                .hits
                .panes
                .iter()
                .find(|hit| contains(hit.inner_rect, point)),
        };
        let Some(hit) = hit else {
            return "";
        };
        self.endpoints
            .iter()
            .find(|endpoint| endpoint.endpoint_id == self.active_endpoint_id)
            .and_then(|endpoint| endpoint.pane_pointer_shapes.get(&hit.pane_id))
            .map_or("", String::as_str)
    }

    /// Returns the shape the host cursor must switch to, if it differs from the last one written.
    pub(crate) fn take_host_pointer_shape_change(&mut self) -> Option<String> {
        let desired = self.hovered_pointer_shape();
        if desired == self.host_pointer_shape {
            return None;
        }
        let desired = desired.to_owned();
        self.host_pointer_shape.clone_from(&desired);
        Some(desired)
    }

    pub(crate) fn forget_host_pointer_shape(&mut self) {
        self.host_pointer_shape.clear();
    }
}
