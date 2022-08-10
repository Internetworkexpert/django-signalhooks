from django import dispatch

post_update = dispatch.Signal(providing_args=["Instance"])
