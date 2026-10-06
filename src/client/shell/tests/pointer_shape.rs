use super::*;
use crate::client::endpoint::ClientEndpointId;
use crate::protocol::endpoint::EndpointPanePointerShape;
use crossterm::event::{KeyModifiers, MouseEventKind};

fn pointer_state() -> ClientShellState {
    let mut state = ClientShellState::new(ClientShellConfig::from_config(&Config::default()));
    state.set_snapshot(Box::new(snapshot()));
    state.set_pane_surface(surface());
    state.compose(106, 20).unwrap();
    state
}

fn pane_origin(state: &ClientShellState) -> (u16, u16) {
    let rect = state.hits.panes[0].inner_rect;
    (rect.x, rect.y)
}

fn move_mouse(state: &mut ClientShellState, column: u16, row: u16) {
    let outcome = state.handle_raw_events(vec![RawInputEvent::Mouse(MouseEvent {
        kind: MouseEventKind::Moved,
        column,
        row,
        modifiers: KeyModifiers::empty(),
    })]);
    assert!(outcome.actions.is_empty());
}

fn set_shape(state: &mut ClientShellState, shape: &str) {
    state.set_endpoint_pane_pointer_shape(
        &ClientEndpointId::Local,
        EndpointPanePointerShape {
            pane_id: "pane_1".into(),
            shape: shape.into(),
        },
    );
}

#[test]
fn hovered_pane_shape_reaches_the_host_only_when_it_changes() {
    let mut state = pointer_state();
    assert_eq!(state.take_host_pointer_shape_change(), None);
    set_shape(&mut state, "pointer");
    assert_eq!(
        state.take_host_pointer_shape_change(),
        None,
        "a shape without a hovered pane keeps the host default"
    );
    let (x, y) = pane_origin(&state);
    move_mouse(&mut state, x, y);
    assert_eq!(
        state.take_host_pointer_shape_change().as_deref(),
        Some("pointer")
    );
    move_mouse(&mut state, x + 1, y + 1);
    assert_eq!(state.take_host_pointer_shape_change(), None);
    set_shape(&mut state, "text");
    assert_eq!(
        state.take_host_pointer_shape_change().as_deref(),
        Some("text")
    );
    set_shape(&mut state, "");
    assert_eq!(state.take_host_pointer_shape_change().as_deref(), Some(""));
    assert_eq!(state.take_host_pointer_shape_change(), None);
}

#[test]
fn host_shape_resets_outside_the_pane_and_outside_terminal_mode() {
    let mut state = pointer_state();
    set_shape(&mut state, "pointer");
    let (x, y) = pane_origin(&state);
    move_mouse(&mut state, x, y);
    assert_eq!(
        state.take_host_pointer_shape_change().as_deref(),
        Some("pointer")
    );
    move_mouse(&mut state, x + 4, y);
    assert_eq!(state.take_host_pointer_shape_change().as_deref(), Some(""));
    move_mouse(&mut state, x + 1, y);
    assert_eq!(
        state.take_host_pointer_shape_change().as_deref(),
        Some("pointer")
    );
    state.mode = ClientShellMode::Navigate;
    assert_eq!(state.take_host_pointer_shape_change().as_deref(), Some(""));
    state.mode = ClientShellMode::Terminal;
    assert_eq!(
        state.take_host_pointer_shape_change().as_deref(),
        Some("pointer")
    );
    state.forget_host_pointer_shape();
    assert_eq!(
        state.take_host_pointer_shape_change().as_deref(),
        Some("pointer"),
        "a forgotten host shape is rewritten on the next sync"
    );
}

#[test]
fn closed_panes_drop_their_shape_with_the_next_snapshot() {
    let mut state = pointer_state();
    set_shape(&mut state, "pointer");
    let mut next = snapshot();
    next.revision = 2;
    next.panes.clear();
    next.focused_pane_id = None;
    state.set_snapshot(Box::new(next));
    let local = state
        .endpoints
        .iter()
        .find(|endpoint| endpoint.endpoint_id == ClientEndpointId::Local)
        .expect("local endpoint");
    assert!(local.pane_pointer_shapes.is_empty());
}
