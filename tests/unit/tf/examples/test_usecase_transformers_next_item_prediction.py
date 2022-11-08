from testbook import testbook

from tests.conftest import REPO_ROOT


@testbook(REPO_ROOT / "examples/usecases/transformers-next-item-prediction.ipynb", execute=False)
def test_usecase_pretrained_embeddings(tb):
    tb.inject(
        """
        import os, random
        from datetime import datetime, timedelta
        from merlin.datasets.synthetic import generate_data
        ds = generate_data('booking.com-raw', 10000)
        if not os.path.exists('~/merlin-models-data/booking'):
            os.makedirs('~/merlin-models-data/booking')
        df = ds.compute()
        def generate_date():
            date = datetime.today()
            if random.randint(0, 1):
                date -= timedelta(days=7)
            return date
        df['checkin'] = [generate_date() for _ in range(df.shape[0])]
        df.to_csv('~/merlin-models-data/booking/train_set.csv')
        """
    )
    # import pdb
    # pdb.set_trace()
    tb.cells[4].source = tb.cells[4].source.replace("get_booking(None)", "")
    tb.cells[30].source = tb.cells[30].source.replace("d_model=40", "d_model=16")
    tb.cells[32].source = tb.cells[32].source.replace("epochs=5", "epochs=1")
    tb.execute()
