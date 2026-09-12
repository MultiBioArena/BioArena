import base64
import time
import asyncio
import shutil
import subprocess

from fastapi.testclient import TestClient
import pytest

from bio_arena.fomo_screens import MAX_AGE, Screen, ScreenFeed, create_app, validate_frame,render_frame


def observation():
    return {'state':'live','path':'/tokens/robinhood/0x'+'1'*40,'captured_at':100,
        'clip':{'x':328,'y':72,'width':1000,'height':500,'scale':1},
        'mask':{'x':700,'y':300,'width':300,'height':200},
        'jpeg':base64.b64encode(b'\xff\xd8fixture\xff\xd9').decode()}


@pytest.mark.parametrize('change',[
    {'path':'/profile/private'}, {'captured_at':1}, {'captured_at':float('nan')},
    {'mask':{'x':700,'y':300,'width':301,'height':200}},
    {'clip':{'x':328,'y':72,'width':10000,'height':500}},
    {'jpeg':'not an image'}, {'jpeg':base64.b64encode(b'html private page').decode()},
])
def test_unpublishable_frame_is_rejected(change):
    with pytest.raises(ValueError):validate_frame({**observation(),**change},101)


def test_expired_or_private_screen_has_no_image_metadata():
    screen=Screen('live',b'image',100,1,'/tokens/robinhood/0x'+'1'*40)
    assert screen.public(101)['state']=='live'
    assert screen.public(100+MAX_AGE+1)=={'state':'stale','captured_at':None,'sequence':1,'page_path':None}
    assert validate_frame({'state':'private_page'},101) is None


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg is required for the optional screen service')
def test_render_covers_account_area_and_keeps_chart_visible():
    data=subprocess.check_output(['ffmpeg','-loglevel','error','-f','lavfi','-i','color=red:s=1000x500',
        '-frames:v','1','-threads','1','-f','image2pipe','-vcodec','mjpeg','pipe:1'])
    valid={**observation(),'jpeg':base64.b64encode(data).decode()}
    assert validate_frame(valid,101)==data
    with pytest.raises(ValueError,match='scale'):
        validate_frame({**valid,'clip':{**valid['clip'],'width':1100}},101)
    image=asyncio.run(render_frame(observation(),data))
    pixels=subprocess.check_output(['ffmpeg','-loglevel','error','-f','image2pipe','-i','pipe:0',
        '-frames:v','1','-threads','1','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],input=image)
    assert len(pixels)==960*540*3
    def pixel(x,y):return tuple(pixels[(y*960+x)*3:(y*960+x)*3+3])
    chart=pixel(300,250);covered=pixel(850,420)
    assert chart[0]>220 and chart[1]<30 and chart[2]<30
    # JPEG/video color ranges can shift a dark fill by several levels. The red
    # source must be replaced with a uniform dark area, not merely dimmed.
    assert max(covered)<40 and max(covered)-min(covered)<12
    assert all(abs(a-b)<3 for a,b in zip(covered,pixel(760,390)))


def test_api_has_no_remote_input_or_raw_browser_channel(monkeypatch):
    monkeypatch.setattr('bio_arena.fomo_screens.public_snapshot',lambda **_: {'fresh':False,'running':False,'bios':[],'orders':[]})
    feed=ScreenFeed({'accounts':{'adult':{'session':'PRIVATE_SESSION','browser_directory':'PRIVATE_DIRECTORY'}}})
    feed.screens['adult']=Screen('live',b'jpeg-fixture',time.time(),2,'/tokens/robinhood/0x'+'1'*40)
    with TestClient(create_app(feed)) as client:
        response=client.get('/api/fomo-screens')
        assert response.status_code==200
        assert 'PRIVATE_' not in response.text and 'jpeg-fixture' not in response.text
        frame=client.get('/api/fomo-screens/adult/frame')
        assert frame.content==b'jpeg-fixture' and frame.headers['content-type']=='image/jpeg'
        assert frame.headers['cache-control']=='no-store'
        assert client.post('/api/fomo-screens/adult/frame',json={'click':True}).status_code==405
        assert client.get('/api/fomo-screens/missing/frame').status_code==404
        feed.screens['adult'].captured_at=time.time()-MAX_AGE-1
        assert client.get('/api/fomo-screens/adult/frame').status_code==503
        feed.screens['adult']=Screen('private_page')
        assert client.get('/api/fomo-screens/adult/frame').status_code==503
