use clap::{ArgMatches, Command};

use crate::api::schema::{EmptyParams, Method, Request};

use super::projection::{self, ParseError};

pub(crate) fn command() -> Command {
    Command::new("sidebar")
        .about("Control the foreground client's sidebar")
        .subcommand_required(true)
        .arg_required_else_help(true)
        .subcommand(Command::new("toggle").about("Collapse or expand the sidebar"))
}

fn request(matches: &ArgMatches) -> Result<Request, ParseError> {
    match matches.subcommand() {
        Some(("toggle", _)) => Ok(Request {
            id: "cli:terminal:sidebar:toggle".into(),
            method: Method::ClientSidebarToggle(EmptyParams::default()),
        }),
        _ => Err(ParseError::Usage("expected sidebar toggle".into())),
    }
}

pub(super) fn run(args: &[String]) -> std::io::Result<i32> {
    match projection::parse(command(), args, request) {
        Ok(request) => super::print_response(&super::send_request(&request)?),
        Err(ParseError::Clap(error)) => super::print_clap_error(&error),
        Err(ParseError::Usage(message)) => {
            eprintln!("{message}");
            Ok(2)
        }
        Err(ParseError::Io(error)) => Err(error),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sidebar_binding_preserves_literal_requests() {
        let args = vec!["toggle".to_string()];
        let actual = projection::parse(command(), &args, request).expect("valid sidebar command");
        assert_eq!(
            serde_json::to_value(actual).expect("request JSON"),
            serde_json::json!({
                "id": "cli:terminal:sidebar:toggle",
                "method": "client.sidebar.toggle",
                "params": {},
            })
        );
    }

    #[test]
    fn sidebar_binding_help_and_invalid_arity_stop_before_transport() {
        command().debug_assert();
        for args in [vec![], vec!["toggle", "extra"], vec!["collapse"]] {
            let args: Vec<_> = args.into_iter().map(String::from).collect();
            assert!(
                matches!(projection::parse(command(), &args, request), Err(ParseError::Clap(error)) if error.exit_code() == 2)
            );
        }
        let args = vec!["toggle".into(), "--help".into()];
        assert!(
            matches!(projection::parse(command(), &args, request), Err(ParseError::Clap(error)) if error.exit_code() == 0)
        );
    }
}
