# Security

FastAPI provides several tools to help you deal with security easily, rapidly, in a standard way, without having to study and learn all the security specifications.

## OAuth2 with Password (and hashing), Bearer with JWT tokens

OAuth2 is a specification that defines several ways to handle authentication and authorization.

It is quite an extensive specification and covers several complex use cases.

It includes ways to authenticate using a "third party".

That's what all the systems with "login with Facebook, Google, Twitter, GitHub" use underneath.

## OAuth2 with Password and Bearer

OAuth2 specifies that when using the "password flow" (that we are using) the client/user must send a `username` and `password` fields as form data.

And the specification says that the fields have to be named like that. So `user-name` or `email` wouldn't work.

But don't worry, you can show it as you wish to your end users in the frontend.

And your database models can use any other names you want.

But for the login endpoint, we need to use these names to be compatible with the specification (and be able to, for example, use the integrated API documentation system).
