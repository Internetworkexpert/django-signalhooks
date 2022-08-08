from django import dispatch

pre_update = dispatch.Signal(providing_args=["Sender", "Instance"])

post_update = dispatch.Signal(providing_args=["Sender", "Instance"])
