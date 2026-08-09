Before Running this kit - user should get to a good go version

curl -sL https://go.dev/dl/go1.24.6.linux-amd64.tar.gz -o /tmp/go.tgz
sudo rm -rf /usr/local/go && sudo tar -C /usr/local -xzf /tmp/go.tgz
export PATH=/usr/local/go/bin:$PATH
sh tests/uat/Toml/setup_harness.sh
