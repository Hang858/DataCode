from sendworker.command_receiver import CommandReceiver, build_recv_api_config


def create_receiver(recv_api_config, on_start_telegram=None, on_start_darknet=None):
    receiver = CommandReceiver(
        build_recv_api_config(
            module=recv_api_config["user_agent"].split("/")[-1],
            connect_url=recv_api_config["connect_url"],
            recv_url=recv_api_config["recv_url"],
            auth_key=recv_api_config["auth_key"],
            request_type=recv_api_config["request_type"],
            command_check_interval=recv_api_config["command_check_interval"],
        ),
        on_start_telegram=on_start_telegram,
        on_start_darknet=on_start_darknet,
    )
    return receiver
