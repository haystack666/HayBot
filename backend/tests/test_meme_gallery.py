from types import SimpleNamespace

import httpx
import pytest

from app.meme_gallery import MemeGallery
from app.memes import MemeCatalog
from app.meme_service import MemeService
from app.store import Store


def entry(name, alt='开心', category='DeepSeek娘'):
    return {'name':name,'alt':alt,'category':category,'description':'一起庆祝好消息',
            'original':f'https://img.aigengtu.com/meme/{name}.webp',
            'preview':f'https://img.aigengtu.com/0_preview/meme/{name}.webp'}


@pytest.mark.asyncio
async def test_remote_gallery_categories_paging_search_and_cache(monkeypatch):
    requests=[]
    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(200,json={'generated_at':'today','gallery':{
            'DeepSeek娘':{'name':'DeepSeek娘','images':[entry('one'),entry('two','委屈')]},
            'Claude娘':{'name':'Claude娘','images':[entry('three','开心','Claude娘')]}}})
    client=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:client(transport=httpx.MockTransport(respond),**kwargs))
    gallery=MemeGallery()
    page=await gallery.list(limit=1,offset=1)
    assert page['total']==3 and page['items'][0]['name']=='two'
    assert [c['count'] for c in page['categories']]==[2,1]
    assert (await gallery.list(category='Claude娘'))['total']==1
    assert (await gallery.list(q='委屈'))['total']==1
    assert len(requests)==1
    assert not gallery.image_url('https://evil.test/a.webp')
    assert not gallery.image_url('https://img.aigengtu.com@evil.test/a.webp')


@pytest.mark.asyncio
async def test_incremental_embedding_only_new_or_semantically_changed_items(tmp_path,monkeypatch):
    library=MemeCatalog(tmp_path/'library')
    store=Store(tmp_path/'bot')
    c=store.load();c.memes.packs=['aigengtu'];c.memes.embedding.provider_id='a'*32;c.memes.embedding.model='test'
    store.save(c)
    service=MemeService(SimpleNamespace(store=store,providers=SimpleNamespace(get=lambda _:None),request=None),library)
    monkeypatch.setattr(service,'fingerprint',lambda:'fixed-model')
    batches=[]
    async def embed(*args,**kwargs):
        texts=args[3];batches.append(len(texts))
        return {'input_tokens':len(texts),'vectors':[[1.,0.] for _ in texts]}
    monkeypatch.setattr('app.meme_service.embed',embed)
    try:
        entries=[entry('one'),entry('two')]
        assert library.sync_gallery(entries)['added']==2
        await service.rebuild();assert batches==[2]
        library.sync_gallery(list(reversed(entries)))
        await service.rebuild();assert batches==[2]
        entries[0]={**entries[0],'alt':'委屈落泪'}
        assert library.sync_gallery(entries)['changed']==1
        assert service.status()['indexed']==1
        await service.rebuild();assert batches==[2,1]
        entries.append(entry('three'))
        library.sync_gallery(entries)
        await service.rebuild();assert batches==[2,1,1]
        library.sync_gallery(entries[1:])
        assert service.status()['total']==2 and service.status()['indexed']==2
        await service.rebuild();assert batches==[2,1,1]
        assert not list(library.assets.iterdir())  # Indexing never downloads image files.
        more=entries[1:]+[entry(f'extra{i}') for i in range(12)]
        library.sync_gallery(more)
        failed=False
        async def flaky(*args,**kwargs):
            nonlocal failed
            if len(args[3])==2 and not failed:
                failed=True
                raise ValueError('temporary provider failure')
            return await embed(*args,**kwargs)
        monkeypatch.setattr('app.meme_service.embed',flaky)
        with pytest.raises(ValueError):
            await service.rebuild()
        assert service.status()['indexed']==12  # 2 old + 10 completed before failure
        await service.rebuild()
        assert batches==[2,1,1,10,2]  # Retry only the missing final two.

    finally:
        await service.close();store.close();library.close()


def test_local_library_excludes_online_metadata_before_pagination(tmp_path):
    import io
    from PIL import Image
    library=MemeCatalog(tmp_path/'library')
    try:
        library.sync_gallery([entry('online-one'),entry('online-two')])
        image=io.BytesIO();Image.new('RGB',(8,8),'blue').save(image,format='PNG')
        local=library.add(image.getvalue(),'本地上传')
        result=library.list(limit=1,exclude_packs=['aigengtu'])
        assert result['total']==1 and [i['id'] for i in result['items']]==[local['id']]
        assert library.list(offset=1,limit=1,exclude_packs=['aigengtu'])['items']==[]
        assert library.list(search='online',exclude_packs=['aigengtu'])['total']==0
        assert library.list()['total']==3  # Online entries remain available for semantic indexing.
    finally:
        library.close()


@pytest.mark.asyncio
async def test_local_library_requires_explicit_opt_in_even_with_legacy_pack_selection(tmp_path, monkeypatch):
    import io
    from PIL import Image
    library=MemeCatalog(tmp_path/'library');store=Store(tmp_path/'bot')
    image=io.BytesIO();Image.new('RGB',(8,8),'blue').save(image,format='PNG')
    local=library.add(image.getvalue(),'本地表情')
    c=store.load();c.memes.enabled=True;c.memes.packs=['custom'];store.save(c)
    service=MemeService(SimpleNamespace(store=store,providers=None),library)
    try:
        assert not store.load().memes.local_enabled
        assert service.selected_packs()==[]
        assert library.list(packs=[])['total']==0
        monkeypatch.setattr(service,'config_stamp',lambda:'same')
        assert not service.current({**local,'selection_stamp':'same'})
        c.memes.local_enabled=True;store.save(c)
        assert service.selected_packs()==['custom']
        assert service.current({**local,'selection_stamp':'same'}) is False  # Unreviewed upload stays disabled.
        local=library.update(local['id'],{'enabled':True})
        assert service.current({**local,'selection_stamp':'same'})
        c.memes.local_enabled=False;store.save(c)
        assert not service.current({**local,'selection_stamp':'same'})
    finally:
        await service.close();store.close();library.close()
