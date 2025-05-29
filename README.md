

## UV

### install uv

https://docs.astral.sh/uv/getting-started/installation/#cargo


macos:
```shell
brew install uv
```


### initialize uv

```shell
make uv-init
# or
make uv-sync
```


## Pelican Documentation

https://docs.getpelican.com/en/latest/index.html

```shell
make help
```


## local HTTPS test

Update /etc/hosts with 
```
127.0.0.1 blog.i544c.com
```

Install mkcert and generate cert [link](https://github.com/FiloSottile/mkcert)

```
$ brew install mkcert nss

$ mkcert -install
Created a new local CA 💥
The local CA is now installed in the system trust store! ⚡️
The local CA is now installed in the Firefox trust store (requires browser restart)! 🦊

$ mkcert blog.i544c.com

Created a new certificate valid for the following names 📜
 - blog.i544c.com

The certificate is at "./example.com+5.pem" and the key at "./example.com+5-key.pem" ✅
```

Update cert path on https server file: `serve_https.py`

Run with cert
```
uv run serve_https.py
```
