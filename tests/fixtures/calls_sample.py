def helper():
    pass


class Service:
    def run(self):
        helper()
        self.prepare()
        os.path.join("a", "b")

        def nested():
            helper()  # should NOT count toward Service.run's calls

        if True:
            self.log.warning("done")
