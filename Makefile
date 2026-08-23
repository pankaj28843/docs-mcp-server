.PHONY: cli cli-install daemon-install daemon-start daemon-stop daemon-restart daemon-status go-test

cli:
	$(MAKE) -C cli build

cli-install:
	$(MAKE) -C cli install

daemon-install:
	$(MAKE) -C cli daemon-install

daemon-start:
	$(MAKE) -C cli daemon-start

daemon-stop:
	$(MAKE) -C cli daemon-stop

daemon-restart:
	$(MAKE) -C cli daemon-restart

daemon-status:
	$(MAKE) -C cli daemon-status

go-test:
	$(MAKE) -C cli test
